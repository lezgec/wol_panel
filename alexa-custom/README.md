# Skill Custom de WoL Pro

Conserva la skill Smart Home que ya enciende tus PC. Esta skill adicional ejecuta las acciones creadas en **Control Windows**.

## Configuración

1. Crea una skill **Custom**, idioma Español (MX, ES o US), nombre de invocación **wol pro**, endpoint AWS Lambda. El nombre puede requerir ajuste si la validación de Amazon lo pide; modifícalo en los tres modelos.
2. Sube `lambda_custom.py` del repositorio a una Lambda Python; handler `lambda_custom.lambda_handler`. Añade el trigger **Alexa Skills Kit** restringido al ID de esta nueva skill.
3. En las variables privadas de Lambda configura `WOL_CUSTOM_BACKEND_URL=https://TU_DOMINIO/alexa/custom` y el mismo `ALEXA_BRIDGE_SECRET` de Azure. No pegues la clave en el código ni en Git.
4. En Azure añade `ALEXA_CUSTOM_SKILL_ID=amzn1.ask.skill.…` y `ENABLE_WINDOWS_AGENT=1` tras ejecutar la migración. Reinicia el servicio existente.
5. Importa el JSON de `skill-package/interactionModels/custom` para el idioma de la skill. Construye el modelo.
6. En **Account Linking**, activa Authorization Code: autorización `https://TU_DOMINIO/oauth/authorize`, token `https://TU_DOMINIO/oauth/token`, credenciales OAuth ya configuradas en `ALEXA_CLIENT_ID` y `ALEXA_CLIENT_SECRET`, autenticación de cliente en el cuerpo. Añade las URLs de retorno exactas que Amazon muestra para esta nueva skill a `ALEXA_REDIRECT_URIS`, **conservando las de la skill Smart Home**. No se requieren scopes adicionales.
7. Habilita desarrollo, vincula tu cuenta desde Alexa y prueba una acción existente: «Alexa, pide a wol pro que ejecute Spotify en mi PC». El backend devuelve «Orden enviada»; comprueba el resultado en el panel.

La Lambda firma las peticiones para Azure. El backend comprueba firma, antigüedad, ID de skill y token OAuth antes de buscar una acción de esa cuenta. No acepta comandos de consola, rutas de Windows ni credenciales del agente por voz.

## Decir «Alexa, abre Spotify en mi PC»

En la app Alexa crea una **rutina** cuyo disparador de voz sea «abre Spotify en mi PC». Como acción personalizada escribe la petición completa que acabas de probar, por ejemplo «pide a wol pro que ejecute Spotify en mi PC». Así el usuario dice su frase breve y la rutina llama a la skill. La opción y ejecución concreta dependen del idioma/región de Alexa; pruébala en tus Echo antes de publicar.

También se incluye la tarea `skill-package/tasks/ExecuteAction.1.json`, con un campo «Nombre de la acción», para seleccionar directamente WoL Pro como acción de rutina. El backend procesa `LaunchRequest.task` y responde con `Tasks.CompleteTask`.

Para registrar la tarea, exporta tu paquete de skill con **ASK CLI v2**, añade la carpeta `tasks` al paquete exportado e impórtalo con el flujo oficial de importación/validación. El paquete de este repositorio contiene los modelos y la tarea; **el manifiesto, ARN y detalles de distribución los genera tu skill real**, no se incluyen valores inventados. Amazon ofrece Custom Tasks en beta y exige validación/certificación para su disponibilidad pública; el código por sí solo no publica la skill ni crea rutinas para otros usuarios.

Referencias: [Tasks y ASK CLI](https://developer.amazon.com/en-US/docs/alexa/custom-skills/implement-custom-tasks-in-your-skill.html), [Integración con rutinas](https://developer.amazon.com/en-US/docs/alexa/custom-skills/integrate-custom-task-with-alexa-routines.html).

## Antes de publicar

Completa la ficha, imágenes, URLs HTTPS de privacidad y términos y pruebas de vinculación de una cuenta nueva, PC desconectado, permiso denegado, cancelación y solicitudes repetidas. Envía a certificación en Amazon. La disponibilidad de la frase breve exige configurar una rutina por usuario.
