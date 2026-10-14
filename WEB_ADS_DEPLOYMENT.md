# Anuncios web de WoL Pro

Preparación del 10 de octubre de 2026, instalada manualmente en Azure por el usuario. Confirmó `WEB_ADS_PREPARADA_SIN_ACTIVAR` y servicio activo. La última consulta de AdSense muestra **Preparando el sitio** y **ads.txt: Autorizado**. Se conserva `ADS_WEB_READY=0`; no requiere otra compilación de Android. Los comandos de instalación siguientes son referencia, no una tarea pendiente.

## Espacios y cuenta

| Elemento | Identificador público |
|---|---|
| Editor | `ca-pub-8703217786138724` |
| Banner superior adaptable | `7179749843` |
| Rectángulo adaptable | `9557581305` |
| Sitio registrado | `luiszamora.dev` |
| Panel | `https://wol.luiszamora.dev` |
| Política | `https://wol.luiszamora.dev/privacy` |

El banner aparece bajo la cabecera y el rectángulo bajo las indicaciones de Alexa/agente en la columna lateral. En móvil la columna se apila. Los espacios vacíos se ocultan. No se añaden anuncios a inicio de sesión, Mi plan, administrador ni cartera pública estática. Los espacios web no son intersticiales ni videos; AdMob gestiona esos formatos en Android.

## Consentimiento de Google

- Mensaje europeo publicado: **WoL Pro web - Consentimiento europeo**, inglés y 31 traducciones; consentimiento, administrar opciones y rechazo habilitados. Logotipo opcional desactivado. Optimización del mensaje desactivada para conservar el flujo de decisión.
- Mensaje estadounidense publicado: **WoL Pro web - Privacidad Estados Unidos**, inglés y español/español latinoamericano, todos los estados admitidos actualmente y en el futuro. Logotipo opcional desactivado.
- Los enlaces del pie permiten volver a abrir las preferencias europeas o rechazar venta/compartición en los estados aplicables.

La etiqueta estándar de AdSense despliega el CMP publicado de Google. Esa carga de Google ocurre solo tras comprobar una cuenta Free elegible y el interruptor web; sirve para obtener las decisiones regionales. Los elementos `ins` y solicitudes `adsbygoogle.push` esperan ambas decisiones. Fuera de una región aplicable se requiere el estado explícito «no aplica». Datos desconocidos, rechazo europeo, exclusión estadounidense, GPC y errores de conexión bloquean los espacios. Se solicitan anuncios no personalizados incluso cuando existe consentimiento; no se envían a AdSense correos, MAC, órdenes ni tokens de compra desde nuestro código.

**Anuncios automáticos y optimización automática desactivados y comprobados en AdSense. Mantenerlos desactivados.** Unidades manuales únicamente: así Google no inserta espacios adicionales fuera del control de plan. AdSense no permite probar inventario real antes de su aprobación. No pulsar anuncios propios durante la comprobación.

Documentación técnica utilizada:

- [API del CMP de Google](https://developers.google.com/funding-choices/fc-api-docs).
- [TCF en AdSense](https://support.google.com/adsense/answer/9804260).
- [Solicitudes no personalizadas y pausa de anuncios](https://support.google.com/adsense/answer/9042142).
- [GPP: interfaz del CMP](https://github.com/InteractiveAdvertisingBureau/Global-Privacy-Platform/blob/main/Core/CMP%20API%20Specification.md).
- [Acceso de rastreo a páginas con autenticación](https://support.google.com/adsense/answer/161351).

## Plan, recompensa y administrador

La web consulta el plan antes de cargar Google y antes de solicitar espacios. Vuelve a comprobarlo cada minuto y al regresar al panel. Premium, cuenta suspendida, recompensa vigente de 30 minutos, publicidad web desactivada o vista excluida retiran los espacios. Un cambio realizado en otro dispositivo se detecta en la siguiente comprobación; no se puede deshacer una petición ya enviada mientras el usuario aún era Free.

La comprobación periódica no refresca anuncios existentes: consulta la política. La selección del CMP y los cambios de plan pueden retirar los espacios; una nueva autorización válida permite mostrarlos nuevamente.

El administrador muestra la preparación web por separado del alcance Android. Para solicitar anuncios web deben cumplirse **todas** estas condiciones:

1. Política maestra de publicidad habilitada y opción web activada en el administrador.
2. `ADS_WEB_READY=1` tras aprobación de AdSense y comprobación del CMP.
3. Usuario incluido en `ADS_WEB_TEST_USER_IDS`, si se configuró un alcance de prueba. Una lista vacía permite cuentas Free elegibles; una lista inválida bloquea la web.
4. Vista `home` permitida, cuenta Free sin pausa y decisiones regionales válidas.

`ADS_TEST_USER_IDS` sigue controlando Android. No amplía ni restringe la web. El instalador preserva la política y todas las variables Android, compras y recompensas.

## Instalación manual

Desde PowerShell:

```powershell
scp 'C:\Users\lezgo\Desktop\wol_panel\artifacts\ads-setup\WoLPro-web-ads-1.1.3.zip' azureuser@130.131.32.129:/home/azureuser/
```

En Azure, compara primero el SHA-256 del ZIP con `WoLPro-web-ads-1.1.3.sha256` o el valor proporcionado al entregar el archivo. Luego:

```bash
bash <<'BASH'
set -euo pipefail
stage="$(mktemp -d /home/azureuser/wol-web-ads-XXXXXX)"
python3 -m zipfile -e /home/azureuser/WoLPro-web-ads-1.1.3.zip "$stage"
sudo bash "$stage/install.sh"
sudo systemctl is-active wol.service
echo "CARPETA_ACTUALIZACION=$stage"
BASH
```

El instalador verifica todos los archivos, comprueba Python/Jinja, respalda los archivos afectados y `.env`, conserva sus permisos y reinicia `wol.service`. Si falla un paso posterior al respaldo, restaura código y entorno. No migra ni modifica bases de datos. Debe imprimir `WEB_ADS_PREPARADA_SIN_ACTIVAR`, `RESPALDO=...` y servicio activo. El paquete contiene `admin-app.js` para `/opt/wolpro_admin/app.js`; no requiere recargar Nginx.

Recarga el panel y administrador con Ctrl+F5 para actualizar JavaScript/CSS. Comprueba que siguen funcionando tus equipos y que el administrador indica «Web pendiente de aprobación/configuración». La cuenta Free no debe cargar Google con `ADS_WEB_READY=0`.

## Activación después de la aprobación

Primero verificar el sitio como Listo en AdSense, ambos mensajes Publicados y anuncios automáticos desactivados. El panel necesita autenticación: después de activarse la cuenta AdSense, revisar la autorización de rastreo y la verificación del sitio en Search Console. No entregar la cuenta personal ni acceso a órdenes reales al rastreador. Si se requiere acceso, preparar una cuenta y entorno de demostración específicamente autorizados.

Tras estos pasos, preparar un respaldo de `.env`, cambiar `ADS_WEB_READY` a `1` conservando inicialmente `ADS_WEB_TEST_USER_IDS=1` y reiniciar `wol.service`. En el administrador activa solo la opción web; conserva el resto de la política de Android. Verifica privacidad/rechazo, Premium y recompensa en el panel antes de ampliar el alcance. Para abrir la web a todas las cuentas Free, dejar vacío `ADS_WEB_TEST_USER_IDS` y reiniciar el servicio. No vaciar `ADS_TEST_USER_IDS` hasta completar las pruebas de Android.

## Validación local y límites

`python -m unittest test_monetization -q` valida 24 casos de planes, cuotas, políticas, recompensas y seguridad. `node --test test_web_ads.cjs` valida 9 escenarios del navegador con proveedores simulados: carga condicionada, ambas regiones, rechazo, revocación, GPC, bases permitidas por TCF y restricciones del editor, cambios durante la carga, errores y espacios vacíos. Las pruebas no solicitan anuncios reales.

Faltan la aprobación externa y la comprobación real del CMP/inventario después de la instalación. Un bloqueador o falta de inventario puede dejar espacios ocultos aunque el sitio esté aprobado; eso no impide usar los controles del PC.
