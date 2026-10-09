# WoL Pro

Para publicar el servicio multiusuario, consulta [DEPLOY_AZURE.md](DEPLOY_AZURE.md).
La configuración completa de la skill está en [ALEXA_SETUP.md](ALEXA_SETUP.md).
Se entregan contenedor, Compose, ejemplo HTTPS y variables de producción; aún
no se ha desplegado en Azure ni completado la vinculación real con Amazon.

Panel Flask con tres métodos de encendido por equipo:

- **Alexa / Echo:** registra nombre y MAC. La skill publica `Alexa.WakeOnLANController`
  y solicita que un Echo compatible envíe el paquete dentro de casa. Se enciende
  desde la app Alexa o por voz; el botón web muestra cómo hacerlo.
- **Router por Internet:** registra nombre, MAC, IPv4 pública o DDNS y puerto UDP
  externo. El botón web envía el paquete al destino público. La skill también
  puede encender estos equipos enviando al router desde el backend.
- **Red local:** conserva el broadcast local de la implementación anterior.

No se entra ni se modifica la configuración de routers. El modo Router requiere
que el propietario ya tenga una conexión pública accesible y Wake-on-WAN configurado
en un router compatible. Elegir el modo no configura el router automáticamente.
El acceso con Amazon sigue oculto: la vinculación de la skill es independiente
del inicio de sesión del panel.

## Ejecutar en este equipo

```powershell
python -m pip install -r requirements.txt
python migrate_db.py
python app.py
```

Abre http://localhost:5000. El servidor usa Waitress. Las credenciales locales
que antes estaban en `app.py` se conservaron en `.env`; no publiques ese archivo.
Para otra instalación, copia `.env.example` a `.env` y completa sus valores.
La conexión actual usa SQL Server `ESCRITORIO`, base `wol_panel`, ODBC Driver 17
y la identidad de Windows que ejecuta Python. `DB_CONNECTION_STRING` permite
usar una cadena distinta. `migrate_db.py` añade `wake_method`, `wake_host` y
`wake_port` a `devices` y crea tablas si faltan. Los equipos existentes mantienen el método `local`;
puedes cambiarlo en **Cambiar método** sin borrar ni volver a registrar el equipo.

Al registrar un equipo se valida y normaliza su MAC. Encender y eliminar usan
formularios POST. El panel informa si el socket pudo enviar el paquete; WoL no
confirma que el equipo haya arrancado. La configuración de BIOS/UEFI y tarjeta
de red debe permitir Wake-on-LAN, y el equipo debe conservar alimentación.

## Vincular Alexa

En **Account Linking** de tu skill, configura:

- Grant type: **Authorization Code Grant**.
- Authorization URI: `https://wol.luiszamora.dev/oauth/authorize`.
- Access Token URI: `https://wol.luiszamora.dev/oauth/token`.
- Client ID y Client Secret: los valores de `ALEXA_CLIENT_ID` y
  `ALEXA_CLIENT_SECRET`. Si no los defines, se usan `MY_CLIENT_ID` y
  `MY_CLIENT_SECRET` para mantener compatibilidad con el cliente anterior.
- Client Authentication Scheme: **HTTP Basic** o credenciales en el cuerpo POST;
  el servidor acepta ambos.
- Copia las **Alexa Redirect URLs** exactas de esa pantalla a
  `ALEXA_REDIRECT_URIS` en `.env`, separadas por comas. No uses URLs de ejemplo.
- PKCE con S256 está soportado cuando Alexa lo envía.

En **Permissions**, habilita **Send Alexa Events**. Copia las credenciales de
esa sección a `ALEXA_EVENT_CLIENT_ID` y `ALEXA_EVENT_CLIENT_SECRET` en `.env`.
Son las credenciales para autorizar el gateway, no las del cliente de Account Linking.
Configura `ALEXA_REGION=NA`, `EU` o `FE` según la región del endpoint de tu skill.
Sin esos valores y las URLs de retorno reales no se puede completar una prueba
contra Amazon: las pruebas automatizadas usan respuestas simuladas.

Reinicia Python después de cambiar `.env`. Usa una cuenta verificada de WoL Pro
para vincular. Desvincula la skill y vuelve a vincularla: los tokens emitidos por
la implementación anterior no identificaban al usuario y ya no se aceptan.

El endpoint de la skill debe entregar la directiva completa, incluido
`payload.scope.token` en Discovery o `endpoint.scope.token` en TurnOn, a
`https://wol.luiszamora.dev/alexa/smarthome`, y devolver el JSON de respuesta sin
envolverlo. Si tu skill usa AWS Lambda, `lambda_function.py` incluye ese puente.
Configura en Lambda `WOL_BACKEND_URL=https://wol.luiszamora.dev/alexa/smarthome`,
handler `lambda_function.lambda_handler`, Python y timeout de al menos 8 segundos.
Configura también `ALEXA_BRIDGE_SECRET` con la misma clave privada de mínimo
32 caracteres en Lambda y backend. Lambda firma la petición y el backend verifica
su firma y fecha. Es obligatorio en producción y adicional al token del usuario.
Conserva el trigger Alexa Smart Home de tu skill. Si ya tienes un puente, revisa
que preserve el token y el JSON de respuesta antes de sustituirlo. También debe
reenviar `Alexa.Authorization.AcceptGrant` con `payload.grantee.token` y `payload.grant.code`.
El backend intercambia y conserva las credenciales del gateway por usuario.

Después de vincular, descubre los dispositivos y di «Alexa, enciende [nombre]».
Solo se descubren y controlan los equipos del usuario vinculado. El encendido
funciona sin una sesión del navegador. La renovación del token está implementada.
El apagado no está implementado: WoL solo enciende y la aplicación devuelve un
error ante TurnOff en vez de anunciar un apagado inexistente.

## Flujo Echo y worker

Para los equipos con método Alexa, Discovery publica la MAC normalizada en
`Alexa.WakeOnLANController.configuration.MACAddresses`. TurnOn devuelve
`Alexa.DeferredResponse`; una cola persistente procesa `WakeUp` y la respuesta
final por el gateway oficial. La directiva se deduplica por `messageId`.
Las órdenes no procesadas caducan en 60 segundos para evitar encendidos tardíos.
El backend no emite UDP para esos equipos. Si cambias el método o la MAC,
vuelve a descubrir dispositivos desde Alexa.

`python app.py` inicia el worker automáticamente junto a Waitress. Si alojas
el backend mediante otro servidor WSGI, ejecuta además `python alexa_worker.py`
como servicio supervisado con las mismas variables y carpeta persistente.
La respuesta final confirma la solicitud de encendido según el protocolo de Alexa;
la app no dispone de un sensor que compruebe que Windows terminó de arrancar.
El flujo oficial necesita una directiva Alexa con `correlationToken`; esta versión
no inventa directivas para encender mediante Echo desde un botón web.

## Estado persistente y red

`instance/session.key` mantiene la clave de sesión y `instance/auth.sqlite3`
guarda códigos de autorización, tokens, desafíos de correo, autorizaciones de Alexa
y la cola de encendido Echo. Las credenciales del gateway también son persistentes.
Los códigos de correo se guardan como hashes, caducan a los 10 minutos y permiten
cinco intentos. La cookie contiene el identificador del desafío, nunca el código.
Los códigos OAuth caducan a los cinco minutos y son de un solo uso; el acceso dura
una hora. Conserva la carpeta `instance` entre reinicios y mantenla privada.
`WOL_STATE_DIR` permite cambiar su ubicación. Esta configuración está pensada
para un único servidor con disco persistente, no réplicas con discos independientes.

Para uso público por HTTPS, configura `COOKIE_SECURE=1`. Para probar por HTTP
en localhost, usa `COOKIE_SECURE=0`. Mantén `.env` e `instance` fuera del control
de versiones; las credenciales conservadas no se rotaron en los proveedores.

En el modo local, el destino predeterminado es `255.255.255.255:9`. Puedes ajustar
`WOL_BROADCAST` y `WOL_PORT`. El backend debe estar en la red de la PC.

En el modo Router, cada equipo tiene su destino público y puerto externo. Se valida
el formato y se impide enviar a direcciones privadas, multicast o de loopback,
incluso si un DDNS resuelve a ellas. Guardar un destino no prueba que el router
lo reenvíe ni que la PC permita WoL desde apagado.

En Azure, utiliza el modo Router para el botón web, o Alexa / Echo para encender
desde Alexa. Migra también SQL Server y conserva el almacenamiento privado
persistente de autenticación. El modo local no alcanza tu LAN desde Azure.
No abras el panel de administración del router ni uses DMZ para esta app.
El puente Lambda transporta directivas HTTP; el Echo o router hace la entrega local.

## Verificación

```powershell
python -m unittest -v test_app
```

Las pruebas usan bases temporales, correo y Amazon simulados, y UDP de loopback;
no despiertan equipos reales ni modifican SQL Server. Para comprobar la recepción
en la LAN puedes ejecutar `python monitor_wol.py` en un equipo encendido de la
misma red. Recibir un paquete no confirma por sí solo el arranque del destino.

Referencia de vinculación:
https://developer.amazon.com/docs/alexaplus/account-linking/account-linking-concepts.html

Referencia del flujo Echo:
https://developer.amazon.com/docs/alexaplus/device-apis/alexa-wakeonlancontroller.html
