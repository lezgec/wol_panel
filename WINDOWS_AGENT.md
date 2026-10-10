# Control Windows y actualización manual

El agente [wolpro_agent](https://github.com/lezgec/wolpro_agent) abre aplicaciones autorizadas y permite apagar el PC con una cuenta atrás cancelable de 30 segundos. Funciona en la sesión de Windows; necesita estar abierto y tener Internet. Se conecta por HTTPS al servidor cada cinco segundos. No necesita puertos entrantes en casa. El encendido sigue usando la integración WoL existente.

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

Reinicia **el servicio que ya utilizas para WoL Pro**. El control Windows aparecerá en el panel. Conserva el endpoint `/alexa/smarthome`. Para ampliar Alexa, actualiza el código de su Lambda existente como se indica abajo. Si necesitas desactivar el nuevo control, vuelve a `ENABLE_WINDOWS_AGENT=0` y reinicia; no elimines tablas.

## Vincular y crear órdenes

1. Ejecuta el agente en el PC; guarda el dominio HTTPS real del servidor.
2. Pulsa **Vincular cuenta**. El navegador abre `/windows/link` con un código público temporal de cinco minutos. Inicia sesión o crea/verifica tu cuenta en el acceso web existente.
3. Confirma el código y selecciona un equipo de tu cuenta, o registra uno con nombre y MAC. La credencial privada llega directamente al agente, se guarda con DPAPI para tu usuario Windows y caduca a los 90 días; entonces vuelve a vincular.
4. Autoriza aplicaciones desde Windows con **Añadir .exe** o **Añadir Spotify**. Spotify debe estar instalado y tener registrado su protocolo. Los ejecutables se abren sin argumentos adicionales. Para apagar, activa el permiso local específico.
5. En **Control Windows**, crea una acción con nombre único (por ejemplo «Spotify en mi PC»), PC y aplicación. Puedes ejecutarla desde el navegador, consultar el resultado y cancelar órdenes pendientes o la cuenta atrás.

Desvincula el PC desde el agente o el panel para revocar su acceso. Si el servidor está inaccesible, el botón del agente informa que no pudo revocar y permite reintentar. Las aplicaciones se ejecutan con los permisos del usuario Windows actual: usa una cuenta normal y autoriza solo aplicaciones de confianza.

Las órdenes caducan a los 60 segundos. Una orden recibida nunca se vuelve a poner en cola. Antes de ejecutar, el agente consulta si sigue autorizada; si el PC se desconecta durante la cuenta atrás, se cancela el apagado. Ante un reinicio después de recibir una orden, el resultado queda «sin confirmar» y no se repite la ejecución. Windows puede bloquear un apagado para proteger trabajo sin guardar; no se fuerza el cierre de aplicaciones.

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
| `commands/claim` | Recibir una orden y cancelaciones |
| `commands/{id}/authorize` | Verificar vigencia/cancelación justo antes del efecto |
| `commands/{id}/report` | Confirmar estado con comprobante privado de recepción |
| `unlink` | Revocar credencial |

El servidor almacena hashes de las credenciales y códigos. Los nombres de aplicaciones y acciones, permisos y resultados sí se guardan en MariaDB. Los paths locales y argumentos no se envían al servidor. El agente guarda credencial, catálogo y comprobantes de órdenes cifrados con DPAPI.
