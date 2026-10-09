# Configurar la skill pública de Alexa

## Qué necesitas

| Recurso/dato | Uso |
| --- | --- |
| Cuenta Amazon Developer | Crear y publicar Smart Home |
| Cuenta AWS y Lambda | Puente de directivas hacia Azure |
| Dominio HTTPS del panel | OAuth y backend público |
| Skill ID y ARN de Lambda | Trigger y endpoint de la skill |
| Client ID y secreto propios de vinculación | `ALEXA_CLIENT_ID`, `ALEXA_CLIENT_SECRET` |
| Redirect URLs reales de la consola | `ALEXA_REDIRECT_URIS` |
| Credenciales de Send Alexa Events | `ALEXA_EVENT_CLIENT_ID`, `ALEXA_EVENT_CLIENT_SECRET` |
| Clave privada compartida de mínimo 32 caracteres | `ALEXA_BRIDGE_SECRET` en Azure y Lambda |
| Idioma, región y mercados | Endpoint Lambda y `ALEXA_REGION` |
| Nombre, descripción, iconos, soporte y cuenta de prueba | Distribución y certificación |

Azure aloja el panel, OAuth, SQL y worker. Lambda es el puente con Alexa; no manda
UDP a casa. Echo entrega el paquete local para el método Alexa; para Router,
el backend envía UDP a la IP pública/DDNS y puerto guardados por el propietario.

## 1. Smart Home y Lambda

En [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask)
crea una skill **Smart Home** y copia su **Skill ID**. No necesitas frases/intents
de una skill Custom para «Alexa, enciende [nombre]».

Para el primer lanzamiento elige español México o Estados Unidos y **North America**.
Crea Lambda en **US East (N. Virginia), `us-east-1`**. Español España corresponde
a Europa y Lambda Ireland (`eu-west-1`), con `ALEXA_REGION=EU` en una instalación
dedicada a esa región. El gateway actual es una región por instalación.

En Lambda utiliza un runtime Python soportado, copia `lambda_function.py`,
handler `lambda_function.lambda_handler`, 256 MB y timeout 8 segundos. Añade el
trigger **Alexa → Alexa Smart Home**, restringido al **Skill ID** de esta skill.

Variables en Lambda:

```text
WOL_BACKEND_URL=https://TU_DOMINIO/alexa/smarthome
ALEXA_BRIDGE_SECRET=LA_MISMA_CLAVE_PRIVADA_DEL_BACKEND
```

Copia el ARN a **Smart Home Service Endpoint**, Default Region y North America
cuando la consola lo requiera. El puente firma cada petición; el backend verifica
firma/fecha además del token OAuth del usuario. No uses una URL pública de función
Lambda como sustituto del trigger Smart Home.

## 2. Account Linking

| Campo de consola | Valor |
| --- | --- |
| Grant type | Authorization Code Grant |
| Authorization URI | `https://TU_DOMINIO/oauth/authorize` |
| Access Token URI | `https://TU_DOMINIO/oauth/token` |
| Client ID | Valor propio de `ALEXA_CLIENT_ID` |
| Client Secret | Valor propio de `ALEXA_CLIENT_SECRET` |
| Authentication Scheme | HTTP Basic |
| Default Access Token Expiration, si aparece | 3600 segundos |
| Scope | Vacío si es opcional; el backend no exige scopes adicionales |
| Privacy Policy URL | `https://TU_DOMINIO/privacy` |

Genera ID y secreto privados para el cliente de esta skill; pon los mismos en
Account Linking y Azure. No son las credenciales del usuario ni las de eventos.
Copia las **Alexa Redirect URLs** exactas que muestra esa pantalla a
`ALEXA_REDIRECT_URIS`, separadas por comas. No inventes una URL ni uses comodines.
El backend conserva `state` y admite PKCE S256 cuando se envía.

## 3. Send Alexa Events

En **Permissions** activa **Send Alexa Events**. Copia Client ID/Secret de
Alexa Skill Messaging a `ALEXA_EVENT_CLIENT_ID` y `ALEXA_EVENT_CLIENT_SECRET`
en Azure. Configura `ALEXA_REGION=NA` para el lanzamiento anterior y reinicia.
El código procesa `AcceptGrant`, guarda permisos por usuario y renueva tokens.

## 4. Probar con hardware real

1. Habilita Development con la cuenta Amazon que utiliza el Echo.
2. Crea y verifica una cuenta del panel. Añade nombre + MAC con método Alexa.
3. Desde la app Alexa habilita la skill, vincula la cuenta del panel y autoriza permisos.
4. Descubre dispositivos: solo deben aparecer los tuyos.
5. Con PC preparada para WoL y Echo en la misma LAN, di «Alexa, enciende PC Escritorio».
   Repite desde el teléfono con datos móviles y comprueba el arranque físico.
6. Prueba otra cuenta del panel y otra Amazon para comprobar el aislamiento.

Amazon lista **Echo Dot** y **Echo Show**, todas las generaciones, como compatibles:
tu Dot y Show 8 sirven como candidatos para probar. **Echo Pop no figura** en
esa lista; no se presenta como compatibilidad confirmada. La PC necesita WoL
habilitado en BIOS/NIC y conservar alimentación.

El encendido por Echo parte de una orden de Alexa con `correlationToken`. El botón
web muestra instrucciones; para encender desde ese botón utiliza Router por
Internet con Wake-on-WAN ya configurado. Esta app no modifica routers.
El apagado no está implementado. Tras cambiar método/MAC, descubre de nuevo;
si existía una vinculación anterior, desvincula y vuelve a vincular.

## 5. Publicar para otras personas

Completa Distribution: nombre, descripción con requisitos WoL/Echo/Router,
idiomas/mercados, iconos y contacto. Publica privacidad y términos; el proyecto
tiene `/privacy` y `/terms`, que debes revisar para tu operación real.
Proporciona una cuenta de prueba verificada y las instrucciones/hardware que
necesite el equipo de certificación para comprobar vinculación y encendido.

Ejecuta las validaciones requeridas y envía a **Certification**. Amazon debe
aprobar y publicar la skill para que otras personas puedan habilitarla en los
mercados elegidos. Subir la web a Azure no publica por sí solo la skill.

## Referencias oficiales

- [Implementación, trigger y regiones Lambda](https://www.developer.amazon.com/docs/alexaplus/smarthome/implement-your-addon.html).
- [WoL y dispositivos Echo compatibles](https://developer.amazon.com/docs/alexaplus/device-apis/alexa-wakeonlancontroller.html).
- [Permisos y credenciales de eventos](https://developer.amazon.com/ja/docs/alexaplus/smarthome/configure-permissions-events.html).
- [Seguridad y credenciales de prueba](https://developer.amazon.com/en-US/docs/alexa/custom-skills/security-testing-for-an-alexa-skill.html).
- [Pruebas y certificación](https://developer.amazon.com/en-US/docs/alexa/devconsole/test-and-submit-your-skill.html).
