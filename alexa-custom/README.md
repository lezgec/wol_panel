# Ampliar la misma skill WoL Pro

Usamos **una sola skill**, el Skill ID existente y su vinculación de cuenta. La ampliamos a **Multi-capability Skill (MCS)**: Smart Home para el encendido actual y Custom para abrir aplicaciones y solicitar apagados.

La carpeta `alexa-custom` contiene el modelo Custom de esa misma skill; no es una segunda skill.

## Configuración en la skill existente

1. Abre **WoL Pro**, la skill que ya funciona, en Alexa Developer Console. En **MODELS**, activa **Custom**, conserva **Smart Home** activo y guarda. Sigue el [procedimiento oficial de ampliación a MCS](https://developer.amazon.com/en-GB/docs/alexa/smarthome/mcs-dev-console.html).
2. En el modelo Custom importa el JSON de `skill-package/interactionModels/custom` para el idioma correspondiente (es-MX, es-ES o es-US). Nombre de invocación: **wol pro**; ajusta el nombre si Amazon lo solicita y construye el modelo.
3. Actualiza **la Lambda existente** subiendo juntos `lambda_function.py` y `lambda_custom.py`. El handler sigue siendo **lambda_function.lambda_handler**. Conserva `WOL_BACKEND_URL=https://TU_DOMINIO/alexa/smarthome` y `ALEXA_BRIDGE_SECRET`. El puente deriva `/alexa/custom` en el mismo dominio; no necesitas una nueva URL en las variables Lambda.
4. Conserva el ARN y trigger Smart Home. Configura el modelo Custom con **el mismo ARN Lambda** y añade allí el trigger **Alexa Skills Kit**, restringido **al mismo Skill ID de WoL Pro**. La Lambda enruta `directive` a Smart Home y `request` al modelo Custom.
5. En Azure añade `ALEXA_SKILL_ID=amzn1.ask.skill.…` con **el ID existente** y `ENABLE_WINDOWS_AGENT=1` después de la migración; reinicia el servicio. El ID no es un secreto. `ALEXA_CUSTOM_SKILL_ID` sigue aceptándose como alias antiguo si no se define `ALEXA_SKILL_ID`, pero no hace falta configurar dos IDs.
6. Conserva la configuración OAuth existente, las URLs de retorno y el permiso **Send Alexa Events**. Comprueba que Account Linking siga usando `https://TU_DOMINIO/oauth/authorize`, `https://TU_DOMINIO/oauth/token`, las credenciales `ALEXA_CLIENT_ID`/`ALEXA_CLIENT_SECRET` y autenticación de cliente en el cuerpo. Si Amazon muestra una URL de retorno diferente tras la ampliación, agrégala a `ALEXA_REDIRECT_URIS` conservando las anteriores. No cambies ni recrees credenciales solo por añadir el modelo.
7. Prueba en desarrollo ambos modelos: encender un equipo como antes y ejecutar una acción existente con «Alexa, pide a wol pro que ejecute Spotify en mi PC». El modelo Custom reutiliza el token OAuth de la cuenta vinculada; si Alexa no lo proporciona, solicita vincular de nuevo **la misma skill**.

Referencias de Amazon: [MCS](https://developer.amazon.com/en-US/docs/alexa/smarthome/about-mcs.html), [Lambda compartida entre modelos](https://developer.amazon.com/en-GB/blogs/alexa/alexa-skills-kit/2020/06/create-an-alexa-multi-capability-skill-to-provide-richer-experiences-to-customers).

## Decir «Alexa, abre Spotify en mi PC»

En la app Alexa crea una **rutina** con disparador de voz «abre Spotify en mi PC». Como acción personalizada escribe la petición completa que acabas de probar: «pide a wol pro que ejecute Spotify en mi PC». El usuario dice su frase breve y la rutina llama al modelo Custom de **WoL Pro**. También puedes asociar «apaga mi PC» a la acción de apagado creada en el panel. Prueba las rutinas en tus Echo según idioma/región.

La tarea `skill-package/tasks/ExecuteAction.1.json` permite seleccionar la acción directamente por su nombre. El backend procesa `LaunchRequest.task` y responde con `Tasks.CompleteTask`; el nombre completo de la tarea empieza por **el Skill ID existente**.

Para registrar la tarea, exporta el paquete de **la skill WoL Pro existente** con ASK CLI v2, incorpora `tasks` y el modelo Custom, y actualiza ese mismo Skill ID mediante el flujo oficial de importación/validación. Conserva el manifiesto real y su sección `apis.smartHome`; añade `apis.custom`. El repositorio contiene modelos y tarea, no un manifiesto que reemplace la configuración existente.

Amazon ofrece Custom Tasks en beta; requieren validación/certificación para disponibilidad pública. Consulta [Tasks y ASK CLI](https://developer.amazon.com/en-US/docs/alexa/custom-skills/implement-custom-tasks-in-your-skill.html) e [integración con rutinas](https://developer.amazon.com/en-US/docs/alexa/custom-skills/integrate-custom-task-with-alexa-routines.html).

## Antes de publicar la ampliación

Prueba ambos modelos en desarrollo: vinculación, encendido, apertura, apagado cancelable, PC desconectado, permiso denegado y peticiones repetidas. Si la skill ya está publicada, envía la **actualización de esa skill** a certificación. Añadir el código al repositorio no modifica tu configuración en Amazon ni publica la ampliación.
