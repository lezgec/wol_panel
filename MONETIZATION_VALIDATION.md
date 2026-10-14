# Validación de monetización — 10 de octubre de 2026

Consultar primero [PENDIENTES_PUBLICACION.md](PENDIENTES_PUBLICACION.md) para el estado vigente. El registro siguiente corresponde a fases anteriores y conserva sus resultados históricos; no implica que las versiones 1.1.3 o 0.4.2 estén pendientes de esos mismos pasos. En la preparación web más reciente pasaron 24 pruebas de monetización y 9 de navegador simulado; no se repitieron los CI antiguos ni se probó inventario Google real. El usuario ya desplegó Azure/administrador, probó el agente 0.4.2 y subió Android 1.1.3 a revisión.

## Comprobaciones locales

- Backend: 154 pruebas de `test_app`, `test_windows_agent` y `test_monetization` pasaron en GitHub. Localmente también pasaron las 17 pruebas finales de monetización y cinco pruebas de acceso/transacciones de base de datos.
- Se comprueban cuotas Free/Premium, selección al vencer, Alexa Discovery, restricciones en cola y antes de ejecutar, cancelación, propiedad de recibos, pagos pendientes/cancelados/expirados, reemplazo de tokens, firma ECDSA sobre la consulta original, recompensa de treinta minutos, frecuencia publicitaria, TOTP, CSRF, suspensión, auditoría, promociones y solicitudes de eliminación.
- App: 24 pruebas pasaron; TypeScript y ESLint sin errores. Exportación de bundles Hermes Android e iOS completada.
- Android nativo: `:app:assembleDebug` completó correctamente con Expo 57, AdMob 17 y Expo IAP 6. El manifiesto corresponde a 1.1.0 / código 3, incluye Billing y bloquea `com.google.android.gms.permission.AD_ID` en modo inicial. El SDK también aporta permisos AdServices; revisar el manifiesto del AAB final y las declaraciones al activar anuncios.
- Windows: 38 pruebas pasaron y la publicación autónoma win-x64 se compiló. Se generaron `artifacts/WoLPro-Agent-win-x64.zip`, `artifacts/WoLPro-Agent-Setup.exe` y sus SHA256. El instalador es 0.4.0 y no está firmado digitalmente. No se instaló sobre el agente del usuario durante esta tarea.
- Admin: `node --check app.js` pasó. Revisión en navegador con cuenta y datos ficticios aislados: acceso TOTP, resumen, detalle de usuario, política de anuncios, confirmación con motivo y auditoría. No se modificó una cuenta real ni Azure.

## Integración continua

Los cuatro repositorios pasaron CI. En [backend y MariaDB](https://github.com/lezgec/wol_panel/actions/runs/38052736699), pasaron 154 pruebas de unidad y **141 pruebas contra MariaDB 11.4 aislada**, incluida la carrera entre dos registros Free para comprobar el bloqueo InnoDB y la cuota. No se ejecutaron contra una base de producción. También pasaron [app](https://github.com/lezgec/wol-pro-app/actions/runs/38052810212), [agente Windows](https://github.com/lezgec/wolpro_agent/actions/runs/38052811967) y [administrador](https://github.com/lezgec/wolpro_admin/actions/runs/38052742759).

## Pendiente de las cuentas reales

Actualización de configuración publicitaria: AdMob Android tiene sus tres
unidades creadas y AdSense sus dos espacios gráficos. Se guardaron IDs públicos
con publicidad desactivada. Las rutas públicas de vendedores y la validación
del ID numérico que Google envía en SSV pasaron con **156 pruebas locales**.
La app pasó TypeScript, ESLint y cuatro comprobaciones de configuración:
Android live sin IDs iOS, rechazo de iOS live sin su ID, bloqueo AD_ID en off y
rechazo de plataformas desconocidas. No se recompiló ni publicó un AAB en esta
actualización. Consulta `GOOGLE_ADS_SETUP.md` para pagos, dominio, consentimiento,
verificación del callback y activación todavía pendientes.

Azure y Admin se despliegan manualmente. Google Play requiere crear productos/oferta, credenciales restringidas, RTDN, reconciliación y compras de prueba. AdMob requiere unidades, UMP y SSV reales; AdSense requiere unidades y CMP. El estado predeterminado no inicia cobros ni solicita anuncios.

El APK de comprobación es debug; no sustituye el AAB firmado con la clave de carga existente. La exportación iOS valida JavaScript, no una compilación Xcode. La validación de compras Apple debe implementarse antes de vender en iOS. La firma digital del instalador Windows y la prueba con el PC físico siguen siendo pasos separados.

Consulta [MONETIZATION_DEPLOYMENT.md](MONETIZATION_DEPLOYMENT.md) para respaldos, instalación manual, configuración y recuperación.
