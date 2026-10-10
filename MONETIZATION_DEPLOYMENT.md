# WoL Pro 1.1 — actualización manual

Código preparado para Free/Premium. Esta entrega **no actualiza Azure, Amazon ni Google Play**, no crea productos de pago y no activa anuncios reales. La primera actualización del backend aplica Free (un equipo, Alexa y apagado) a cuentas sin una compra verificada o cortesía vigente.

## Repositorios y orden

1. `wol_panel`: backend, web y permisos de Alexa. Copia todos los archivos de la entrega, no solamente `app.py`.
2. `wolpro_admin`: interfaz administrativa independiente, disponible en `https://github.com/lezgec/wolpro_admin`. Requiere un hostname HTTPS propio y proxy al backend.
3. `wolpro_agent`: agente Windows 0.4.0. Conserva vinculación, aplicaciones, comandos y permisos al actualizar.
4. `wol-pro-app`: app 1.1.0, código Android 3. Genera y firma un **nuevo** AAB en Android Studio.

## Respaldo antes de cambiar Azure

Trabaja dentro de la carpeta `wakeonlan` que ya usa tu `wol.service`. Revisa su ruta y entorno con `sudo systemctl cat wol.service`. Usa el Python/venv configurado allí en los comandos siguientes.

1. Detén el servicio: `sudo systemctl stop wol.service`.
2. Guarda una copia privada de los archivos actuales, la configuración del servicio, `.env` y **todo `WOL_STATE_DIR`**. Si no está definido, es `instance/` dentro del proyecto. Ese directorio contiene sesiones, Alexa, planes, compras, recompensas y claves administrativas. No lo reemplaces por una carpeta vacía ni lo subas a GitHub. Limita los permisos del respaldo al propietario.
3. Respalda también MariaDB: `mysqldump -u wol_user -p wol_panel > /ruta/privada/wol-panel-respaldo.sql`. La contraseña se introduce al solicitarla. Cambia nombres si tu configuración es distinta.
4. Copia el código nuevo manteniendo `.env`, `instance/`, descargas del instalador y el resto de tus datos.
5. Instala dependencias en el venv actual: `python -m pip install -r requirements.txt`.
6. La migración de planes añade tablas `plan_*`, `ad_tickets`, `admin_*` y `deletion_requests` de forma idempotente a `auth.sqlite3`. No elimina equipos ni modifica los comandos locales. Conserva la migración anterior `database/windows_agent.sql` si todavía falta en tu instalación. Ejecuta `python -c "import app; print('Backend y tablas de planes preparados')"` con el mismo entorno que el servicio.
7. La cuota de registro utiliza transacciones y `SELECT ... FOR UPDATE` en la fila del usuario MariaDB. Mantén las tablas de negocio en InnoDB; `migrate_db.py` y las pruebas de MariaDB verifican ese requisito.
8. Inicia manualmente: `sudo systemctl start wol.service`; comprueba `sudo systemctl status wol.service` y el registro del servicio. Revisa `/mi-plan`, inicio de sesión, un apagado y la cancelación de su cuenta atrás.

Los equipos extra quedan guardados e inactivos en Free. Mi plan permite elegir el equipo principal. Al vencer Premium no se borran equipos ni acciones. Las órdenes de aplicaciones y comandos se verifican en la cola común y otra vez antes de ejecutar; las cancelaciones siguen disponibles. El encendido por router queda rechazado y oculto; convierte sus equipos guardando el método Alexa. No hace falta cambiar la skill para aplicar las restricciones: se comprueban en Azure.

## Administrador y pruebas de Premium sin cobros

1. Define `ADMIN_ORIGIN=https://tu-host-admin` en el entorno del backend (sin `/` final).
2. En Azure ejecuta `python admin_bootstrap.py --email tu-correo`. Debe existir y estar verificada la cuenta. Introduce su contraseña, guarda la clave mostrada en tu autenticador y confirma un código. Este comando crea el propietario y deja auditoría. No hay alta administrativa pública ni propietario predeterminado.
3. Publica los archivos estáticos de `wolpro_admin` en su hostname, con TLS y `/api/admin/v1/` dirigido al puerto actual de `wol.service`. Adapta su `nginx.example.conf`; el backend y la interfaz deben compartir el origen administrativo mediante el proxy. No actives CORS abierto.
4. Entra con contraseña y un nuevo código TOTP. La sesión es independiente y dura 30 minutos. Puedes dar una cortesía con fecha y motivo para probar Premium mientras se configura Google Play. La cortesía no representa una compra ni genera cargos.
5. Prueba Free con un equipo, Premium con varios, vencimiento, selección del equipo principal, apertura de apps y bloqueo desde Alexa. No cambies los permisos de Windows para simular el plan; ambos controles son independientes.

Suspender impide operar e invalida sesiones/Alexa; revocar accesos además desvincula agentes y solicita cancelar órdenes pendientes. La auditoría registra administrador, momento, destino, motivo y cambios. La administración inicial dispone de propietarios; roles de soporte y reportes financieros de AdMob se integrarán después de configurar esas cuentas.

## Google Play: configurar al final

1. Crea una suscripción `wolpro_premium` con dos planes base de renovación automática: mensual USD 2,99 y anual USD 24,99. Configura impuestos y precios locales en Play Console.
2. En el plan anual crea una oferta con **un período anual a USD 19,99**, seguido del plan anual normal a USD 24,99. Usa la etiqueta `intro-year` y elegibilidad de nuevos suscriptores. La app muestra fases y precios reales que devuelve Google. Mi plan y el administrador distinguen precios de referencia de precios reales de tienda. Las fechas administrativas controlan la visibilidad en WoL Pro; configura también la duración/elegibilidad en Play Console.
3. Concede a una cuenta de servicio el permiso mínimo de consulta/gestión de suscripciones de esta app en Play Console. Guarda su JSON fuera del código, con acceso exclusivo del servicio.
4. Define en Azure:

   ```dotenv
   GOOGLE_PLAY_PACKAGE=dev.luiszamora.wolpro
   GOOGLE_PLAY_PRODUCTS=wolpro_premium
   GOOGLE_PLAY_CREDENTIALS=/ruta/privada/google-play-service.json
   BILLING_ACCOUNT_SECRET=una-clave-aleatoria-exclusiva-y-persistente
   GOOGLE_RTDN_AUDIENCE=https://wol.luiszamora.dev/api/billing/google/rtdn
   GOOGLE_RTDN_SERVICE_EMAIL=cuenta-push@tu-proyecto.iam.gserviceaccount.com
   ```

   Genera `BILLING_ACCOUNT_SECRET` una vez y respáldala. No la cambies al rotar `FLASK_SECRET_KEY`: vincula los recibos con el identificador ofuscado de la cuenta.

5. Configura notificaciones en tiempo real (RTDN) de Google Play mediante Pub/Sub autenticado con esa audiencia y cuenta de servicio. El endpoint verifica el JWT, el paquete y vuelve a consultar a Google; no acepta Premium enviado por el teléfono.
6. Programa `python billing_reconcile.py` con el entorno del servicio cada 15 minutos (por ejemplo, un timer de systemd). Complementa RTDN para reembolsos, revocaciones y fallos de notificación. Antes de operar, una compra con verificación de más de cinco minutos se consulta nuevamente; si falla esa verificación, la operación no se autoriza. Cancelar renovación conserva acceso hasta vencer; un pago pendiente no da Premium.
7. Añade verificadores de licencia, sube el nuevo AAB a prueba interna y prueba compras de prueba, restauración, cancelación, vencimiento, reembolso y cambio de cuenta. El mismo token no puede concederse a dos cuentas WoL Pro.

Hasta completar todos los valores requeridos, el backend declara compras desactivadas. La app no inicia Billing. No hay checkout web alternativo ni compras por voz. El proyecto incluye el módulo multiplataforma de compras, pero la verificación Apple/App Store no está activada ni implementada en esta entrega: será necesaria antes de vender Premium en iOS.

## AdMob y AdSense: configurar al final

La política inicial tiene publicidad desactivada, banner superior, video voluntario de **30 minutos sin publicidad**, intersticial de hasta uno por 10 minutos y tres por día. Windows no lleva anuncios. Premium y las cuentas con recompensa vigente no solicitan publicidad. La recompensa se concede por una firma ECDSA de AdMob verificada, es idempotente y no cambia los permisos Free.

1. Crea las apps Android/iOS y los espacios de banner, intersticial y rewarded en AdMob. Configura los mensajes UMP de consentimiento/privacidad. Se solicitan anuncios no personalizados; revisa las declaraciones y los proveedores antes de activarlos.
2. Configura la verificación del rewarded con callback `https://wol.luiszamora.dev/api/ads/ssv`. Guarda en Azure `ADMOB_REWARDED_UNIT` con el ID exacto de ese espacio. La app envía como `custom_data` un ticket temporal emitido por el servidor; el cliente no concede la recompensa.
3. En la app establece `EXPO_PUBLIC_ADS_MODE=live` y los App IDs y unidades descritos en su `.env.example`, vuelve a generar el proyecto y compila otro AAB. Los valores de AdMob son identificadores públicos; no pongas credenciales de servicio en variables `EXPO_PUBLIC_*`. El modo predeterminado es `off`. Los App IDs que acompañan el código son de prueba oficiales, con medición retrasada y sin solicitudes por defecto.
4. Para staging usa `EXPO_PUBLIC_ADS_MODE=test` y dispositivos de prueba. Los anuncios de prueba no acreditan una recompensa real; la firma, la cuota y la recompensa se verifican en los tests aislados. Nunca simules callbacks en producción.
5. La pausa natural de intersticiales es regresar de Dispositivos a Inicio después de diez minutos de sesión. No se muestran al abrir la app, al dar órdenes, durante órdenes pendientes ni en una cuenta atrás. El SDK controla la X y la duración; no se fuerza un bloqueo propio de 30 segundos. La cuota es conservadora: reservar un ticket cuenta aunque no haya inventario.
6. Para web define `ADSENSE_CLIENT`, `ADSENSE_BANNER_SLOT` y `ADSENSE_RECTANGLE_SLOT`, y configura un CMP certificado. Conecta su permiso con `window.wolAdsConsent=true` y el evento `wol-ads-consent`; sin este permiso los espacios permanecen ocultos y no se carga AdSense. Usa los anuncios fuera de los controles. La WebView de la app no carga anuncios web.
7. Tras revisar consentimiento, las unidades y las declaraciones, define `ADS_LIVE_READY=1` en Azure y activa los formatos/pantallas desde el administrador. El interruptor global y cada cambio se auditan. No basta con modificar el texto de una promoción para crear un precio o espacio de Google.
8. Actualiza Play Console: declaración de anuncios, identificador publicitario si el AAB lo incluye, Seguridad de datos, privacidad y acceso para revisión. El build predeterminado bloquea `AD_ID`; el build `live` permite el permiso aportado por el SDK, por lo que debe declararse. Revisa el manifiesto final y las prácticas reales de los SDK. No publiques afirmaciones de «sin SDK publicitario» para la versión 1.1.

## Solicitudes de eliminación

El enlace público conserva la solicitud por correo sin iniciar sesión y añade, con sesión, una solicitud autenticada que aparece en Admin. Soporte verifica identidad, cancela/revoca accesos, elimina datos de negocio y estado privado y documenta cualquier conservación legal de facturación o seguridad. La suscripción de tienda se cancela por separado. Marcar «completed» en Admin solo registra el estado; **no borra datos**. No marques una solicitud terminada hasta haber realizado el procedimiento. No hay borrado automático irreversible en esta entrega.

## Recuperación

Si falla la actualización, detén el servicio, guarda el estado actual para diagnóstico y restaura los archivos/entorno del respaldo. No borres las tablas nuevas ni sobrescribas comprobantes recientes sin reconciliarlos. Antes de activar pagos reales, confirma que la versión restaurada sigue aplicando permisos; el backend anterior carece de límites Premium. Mantén compras/anuncios desactivados hasta resolver el incidente. Una reinstalación del agente no exige borrar su configuración protegida.

## Verificación realizada y pendiente

Los comandos de validación son `python -m unittest test_app test_windows_agent test_monetization -q`, `dotnet test wolpro_agent.sln`, y en móvil `npm test`, `npm run typecheck`, `npm run lint` más compilación Android. La CI añade MariaDB aislada y una carrera de registro con dos solicitudes reales. Los resultados finales se documentan en `MONETIZATION_VALIDATION.md`.

Quedan para tus cuentas reales: desplegar Azure/Admin, alta de propietario y autenticador, cuentas AdMob/AdSense, ofertas/productos/RTDN, compras y recompensas de prueba de tienda, firma AAB e instalación desde Play. iOS necesita build de Xcode y validación Apple. No se ha iniciado un cobro ni activado un anuncio real.

Referencias oficiales: [validación de compras](https://developer.android.com/google/play/billing/security), [notificaciones y backend](https://developer.android.com/google/play/billing/backend), [AdMob SSV](https://developers.google.com/admob/android/ssv), [recompensas](https://support.google.com/admob/answer/7313578), [Expo IAP](https://www.openiap.dev/docs/setup/expo), [AdMob React Native](https://docs.page/invertase/react-native-google-mobile-ads).
