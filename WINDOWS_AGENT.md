# Control de PC y actualización manual

El agente [wolpro_agent](https://github.com/lezgec/wolpro_agent) abre aplicaciones autorizadas, inicia comandos CMD/PowerShell personalizados y permite apagar el PC con una cuenta atrás cancelable de 30 segundos. Funciona en la sesión de Windows; necesita estar abierto y tener Internet. Se conecta por HTTPS al servidor cada cinco segundos. No necesita puertos entrantes en casa. El encendido sigue usando la integración WoL existente.

## Estado desde el arranque (agente 0.3.2)

Actualiza el backend, ejecuta `python migrate_db.py` con su entorno Python activado y reinicia el servicio web. Añade la tabla `agent_presence` sin borrar cuentas, equipos, acciones ni vinculaciones. Copia el instalador 0.3.2 a la misma ruta de descargas; conserva `WOL_STATE_DIR` y la configuración Alexa.

En Windows abre el agente vinculado y pulsa **Activar / actualizar servicio** en **Cuenta y vinculación**. Acepta UAC. Se instala `WoLProPresence` con inicio automático y cuenta `LocalService`; no guarda tu contraseña Windows ni activa el inicio de sesión automático. Sus binarios protegidos están en `%ProgramFiles%\WoL Pro\Presence`; la credencial limitada, cifrada con DPAPI de máquina y protegida por ACL, está en `%ProgramData%\WoLPro\Presence`. No copia los scripts ni el catálogo del usuario.

El panel actualiza las tarjetas cada cinco segundos: **PC conectado · agente de sesión sin conexión** confirma comunicación desde el servicio; **PC conectado · control disponible** indica que el agente interactivo también responde. Las aplicaciones, comandos y apagado integrado siguen necesitando iniciar sesión y ejecutar ese agente. **Sin conexión** significa ausencia de comunicación reciente; no demuestra que el equipo esté apagado.

Para verificar el caso real, reinicia voluntariamente tu PC y, sin iniciar sesión en él, abre el panel desde el teléfono. Necesita red disponible antes del inicio de sesión; un PIN BitLocker previo al arranque de Windows impide ejecutar el servicio.

El servicio solo comunica presencia con una credencial distinta a la del agente: no puede consumir órdenes, autorizar comandos ni cambiar el catálogo. Comparte la caducidad de la vinculación (90 días); después de volver a vincular o actualizar el agente, pulsa **Activar / actualizar servicio** para renovar su configuración y copia protegida. Desvincular invalida también la credencial del servicio. **Desactivar servicio** revoca su acceso y pide UAC para retirar el componente local. El desinstalador solicita UAC para retirarlo si existe; si cancelas, el componente independiente queda instalado.

## Actualizar tu servidor Azure

Dentro del checkout del servidor, con su entorno Python activado:

```bash
git pull --ff-only origin main
python -m pip install -r requirements.txt
python migrate_db.py
```

La migración añade cinco tablas `agent_*` y conserva las cuentas/equipos existentes. Usa el mismo `.env`, MariaDB, `FLASK_SECRET_KEY` y directorio `WOL_STATE_DIR`; conserva también tus copias de seguridad habituales. En el `.env` existente añade:

```dotenv
ENABLE_WINDOWS_AGENT=1
# Skill ID existente de WoL Pro, al habilitar su modelo Custom:
ALEXA_SKILL_ID=
```

Reinicia **el servicio que ya utilizas para WoL Pro**. El Control de PC aparecerá al expandir un equipo del panel. Conserva el endpoint `/alexa/smarthome`. Para ampliar Alexa, actualiza el código de su Lambda existente como se indica abajo. Si necesitas desactivar el nuevo control, vuelve a `ENABLE_WINDOWS_AGENT=0` y reinicia; no elimines tablas.

## Vincular y crear órdenes

1. Ejecuta el agente en el PC; guarda el dominio HTTPS real del servidor.
2. Pulsa **Vincular cuenta**. El navegador abre `/windows/link` con un código público temporal de cinco minutos. Inicia sesión o crea/verifica tu cuenta en el acceso web existente.
3. Confirma el código y selecciona un equipo de tu cuenta, o registra uno con nombre y MAC. La credencial privada llega directamente al agente, se guarda con DPAPI para tu usuario Windows y caduca a los 90 días; entonces vuelve a vincular.
4. Autoriza aplicaciones desde Windows con **Añadir aplicación (.exe)** o **Añadir Spotify**. Spotify debe estar instalado y tener registrado su protocolo. Para scripts o aplicaciones con argumentos, usa **Añadir comando**, elige CMD/Windows PowerShell, escribe tu script y activa **Permitir mis comandos de consola**. Incluye ejemplos editables de apagar, reiniciar y abrir una aplicación; guardar no ejecuta nada. Para el apagado integrado, activa su permiso local específico.
5. En el panel, expande la tarjeta de tu equipo. En **Control de PC**, pulsa **Crear una acción**, elige un nombre único (por ejemplo «Spotify en mi PC») y **Ejecutar aplicación o comando**, seleccionando la entrada autorizada. Puedes ejecutarla desde esa tarjeta, consultar el historial y cancelar órdenes pendientes o la cuenta atrás del apagado integrado.

El botón **Añadir equipo** abre el formulario en el mismo panel. Las tarjetas empiezan minimizadas; al expandirlas también puedes modificar el nombre, la MAC y el método de encendido, vincular o desvincular el PC y eliminarlo. Las rutas anteriores `/windows` y `/windows/link` muestran este mismo panel para conservar los enlaces del agente. Esta reorganización no añade tablas ni cambia la skill o el protocolo del agente.

Desvincula el PC desde el agente o el panel para revocar su acceso. Si el servidor está inaccesible, el botón del agente informa que no pudo revocar y permite reintentar. Las aplicaciones se ejecutan con los permisos del usuario Windows actual: usa una cuenta normal y autoriza solo aplicaciones de confianza.

Las órdenes caducan a los 60 segundos. Una orden recibida nunca se vuelve a poner en cola. Antes de ejecutar, el agente consulta si sigue autorizada; si el PC se desconecta durante la cuenta atrás, se cancela el apagado. Ante un reinicio después de recibir una orden, el resultado queda «sin confirmar» y no se repite la ejecución. Windows puede bloquear un apagado para proteger trabajo sin guardar; no se fuerza el cierre de aplicaciones.

Los comandos personalizados se ejecutan sin consola visible y con los permisos de la sesión Windows, sin elevación automática. No usan los 30 segundos de cancelación ni el permiso del apagado integrado: por ejemplo, `shutdown.exe /r /t 0` solicita reiniciar inmediatamente. Desactivar su permiso retira los comandos del catálogo y bloquea las órdenes aún no iniciadas, pero no detiene procesos iniciados. «Solicitud procesada» confirma el inicio de la consola; el agente muestra el código de salida en su actividad local cuando termina. La salida de texto no se envía al servidor. Esta ampliación reutiliza IDs/nombres del catálogo y órdenes `launch`; no añade columnas, tablas ni parámetros de script a la API.

## Alexa

**Una sola skill WoL Pro:** amplía la skill existente a Multi-capability Skill (MCS). Su modelo Smart Home conserva el encendido y su modelo Custom ejecuta las acciones del panel, incluidos los apagados autorizados en Windows. Una rutina puede asociar «Alexa, apaga mi PC» a la acción «Apagar mi PC». El acuse de la skill confirma que se envió la orden; consulta en el panel si el agente la recibió o canceló. Enviar y cancelar órdenes también funciona desde el navegador sin Alexa.

Añade el modelo **Custom a la misma skill** siguiendo [alexa-custom/README.md](alexa-custom/README.md). Allí están las instrucciones para reutilizar el Skill ID, la Lambda y la vinculación OAuth existentes, modelos en español y tarea para rutinas. La frase «Alexa, abre Spotify en mi PC» se asocia a una rutina del usuario. Las órdenes nativas Smart Home `TurnOff` siguen rechazándose, ya que programar una cuenta atrás no permite confirmar que el PC esté apagado; el apagado se pide mediante una acción del modelo Custom de WoL Pro.

## API del agente

Todos los POST exigen JSON. Solo `pair/start` y `pair/poll` son públicos; el resto exige `Authorization: Bearer <credencial del agente>`, sin sesión web. Los formularios del panel mantienen CSRF y autorización por propietario.

| Ruta bajo `/api/agent/v1/` | Función |
| --- | --- |
| `pair/start` | Nombre del PC → códigos temporal público y privado |
| `pair/poll` | Código privado → espera HTTP 428 o credencial una sola vez |
| `heartbeat` | Catálogo de IDs/nombres y permiso local de apagado |
| `presence/register` | Credencial limitada de conexión, solicitada por el agente vinculado |
| `presence/heartbeat` | Confirma conexión; solo admite la credencial de servicio y JSON vacío |
| `presence/revoke` | Retira la credencial de servicio desde el agente vinculado |
| `commands/claim` | Recibir una orden y cancelaciones |
| `commands/{id}/authorize` | Verificar vigencia/cancelación justo antes del efecto |
| `commands/{id}/report` | Confirmar estado con comprobante privado de recepción |
| `unlink` | Revocar credencial |

El servidor almacena hashes de las credenciales y códigos. Los nombres del catálogo y acciones, permiso de apagado y resultados sí se guardan en MariaDB. Los paths locales, argumentos y texto de comandos no se envían al servidor. El permiso de consola se aplica en el PC filtrando el catálogo publicado y revisándolo antes de iniciar. El agente guarda credencial, catálogo y comprobantes de órdenes cifrados con DPAPI. CMD usa un archivo temporal local, eliminado al terminar la consola.

## Descargable desde el panel

El agente vive en el repositorio independiente y privado [wolpro_agent](https://github.com/lezgec/wolpro_agent). Al publicar un tag de versión (por ejemplo `v0.3.1`), su workflow ejecuta pruebas, compila Windows x64 con el runtime incluido, verifica el instalador en una carpeta de pruebas y adjunta `WoLPro-Agent-Setup.exe`, ZIP portátil y hashes SHA256 a una Release.

Las Releases de un repositorio privado requieren acceso a ese repositorio. Para que los usuarios del panel no necesiten cuenta GitHub, la web sirve una copia del instalador desde Azure mediante `GET /windows/download`, con la sesión de WoL Pro y `ENABLE_WINDOWS_AGENT=1`. No hay tokens GitHub en el navegador ni es necesario hacer público el código.

Al actualizar Azure:

1. Ejecuta `git pull --ff-only origin main` en `wol_panel`.
2. Descarga `WoLPro-Agent-Setup.exe` y su `.sha256` desde la Release, con tu cuenta GitHub. También puedes generarlos localmente con `scripts/Build-Installer.ps1` (requiere Inno Setup 6).
3. Copia ambos al servidor y verifica el hash con `sha256sum -c WoLPro-Agent-Setup.exe.sha256` desde la carpeta que los contiene.
4. Coloca el `.exe` en `WOL_STATE_DIR/downloads/WoLPro-Agent-Setup.exe`, legible por el usuario del servicio. Con `WOL_STATE_DIR=/var/lib/wol-pro`, la ruta es `/var/lib/wol-pro/downloads/WoLPro-Agent-Setup.exe`. Crea `downloads` si no existe. Si habías configurado `WOL_AGENT_DOWNLOAD_PATH` con el ZIP, cambia ese valor por la ruta del instalador (o déjalo vacío para usar la ubicación predeterminada). No cambies la carpeta de estado existente.
5. Reinicia tu servicio. En el panel aparecerá **Descargar agente para Windows**. Si falta el archivo, aparece «Descarga disponible próximamente».

El instalador y el ZIP no se guardan en Git ni contienen credenciales. Los ficheros permanecen en la carpeta de estado al actualizar el código. La copia a Azure sigue siendo manual. Hasta que copies el instalador, el panel sigue ofreciendo el ZIP existente en esa carpeta, con sus instrucciones de descompresión.

El instalador se abre en el PC Windows, nunca en Azure. Instala para el usuario actual, crea el acceso del menú Inicio, incluye desinstalador y ofrece escritorio e inicio en bandeja como opciones. Al actualizar o desinstalar, conserva la vinculación y los comandos fuera de su carpeta de programas. El instalador todavía no tiene firma digital del editor; Windows puede mostrar un aviso.
