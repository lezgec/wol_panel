# Tour de WoL Pro

El panel ofrece **Tour de WoL Pro** en la barra superior. Se presenta en la primera visita de la cuenta en ese navegador, después del acceso, y puede retomarse o reiniciarse. El progreso se guarda localmente por cuenta; cambiar de navegador o borrar sus datos puede volver a mostrarlo. Si el almacenamiento está bloqueado, permanece disponible manualmente.

Los nueve pasos cubren registro por nombre/MAC, Alexa, tarjetas del equipo, instalación y vinculación del agente, conexión desde el arranque, apagado protegido, aplicaciones/comandos Premium y Mi plan. Si Control de PC está deshabilitado, omite sus pasos. **Mostrar sección** cierra el diálogo y resalta el lugar correspondiente; vuelve a abrir el tour para continuar. Los ejemplos no crean equipos, envían órdenes ni compran suscripciones.

El tour de la web no aparece automáticamente dentro de la WebView móvil, sobre un diálogo de vinculación abierto ni al confirmar una vinculación. El cliente móvil ofrece su propia guía nativa. No se añaden tablas, permisos ni endpoints.

Comprobación: `node --test test_tour.cjs`. La revisión de navegador usa una cuenta y datos temporales, con comprobaciones de primera visita, reanudación, finalización, secciones reales y pantalla pequeña.
