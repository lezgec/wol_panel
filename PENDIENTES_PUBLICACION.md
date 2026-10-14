# WoL Pro: estado y próximos pasos

Actualizado con las confirmaciones del usuario y la última consulta de AdSense del 10 de octubre de 2026. No es una nueva comprobación de las consolas. Las instrucciones de despliegue anteriores se conservan como referencia; no deben ejecutarse de nuevo por aparecer como pendientes en notas históricas.

## En espera de Google

| Elemento | Último estado confirmado | Al quedar disponible |
|---|---|---|
| Android 1.1.3 / código 5 | Subida por el usuario a prueba cerrada; en revisión | Instalar desde Play y completar las pruebas de anuncios y de las correcciones de interfaz. |
| AdSense, luiszamora.dev | Preparando el sitio; ads.txt Autorizado | Revisar CMP e inventario con alcance limitado antes de abrir anuncios web a todos los usuarios Free. |
| AdMob | Debe revisarse; sin ficha pública vinculada en la última consulta | Vincular la ficha pública cuando exista y comprobar la aprobación. El enlace de prueba interna no sustituye la ficha. |
| Publicación mundial en producción | Alpha ampliada a 178 países/regiones; catálogo de suscripciones en 175 mercados compatibles | Comprobar por separado los países y requisitos de producción antes de publicar. Alpha no publica producción. |

## Trabajo ya terminado y confirmado

- Azure y administrador actualizados: tres formatos Android limitados a la cuenta de prueba 1. No repetir la instalación ni ampliar todavía ese alcance.
- Preparación web instalada por el usuario: `WEB_ADS_PREPARADA_SIN_ACTIVAR` y servicio activo. `ADS_WEB_READY=0` impide solicitar publicidad aunque se active el interruptor web del administrador.
- AdSense: banner y rectángulo manuales, mensajes europeos y estadounidenses publicados, anuncios automáticos y optimización automática desactivados.
- AdMob: tres unidades, teléfonos de prueba registrados, mensajes de consentimiento y callback SSV de consola configurado y verificado. La prueba de consola no concede minutos.
- Billing: credencial y entorno configurados, notificaciones RTDN de prueba recibidas con HTTP 200 y reconciliación cada 15 minutos activa (`checked: 1`, `failed: 0`).
- Compras mensual/anual probadas, cancelación manteniendo Premium hasta el vencimiento y regreso a Free confirmados. Algunas compras necesitaron restauración manual; verificar la corrección en la versión nueva.
- Free conserva un equipo activo; Premium admite hasta diez. Los equipos y acciones se conservan al vencer. Encendido con Alexa, apagado, cancelación, Spotify y comandos autorizados probados.
- Agente Windows 0.4.2: servicio al arrancar probado y nuevo instalador publicado en Azure. Solo se elimina el encendido por router; las órdenes actuales por Internet se conservan.

## Avance independiente de las aprobaciones

1. **Preparar las declaraciones de publicación:** revisar anuncios, ID publicitario, Seguridad de datos y descripción de Free/Premium usando [DECLARACIONES_PLAY_1.1.3.md](DECLARACIONES_PLAY_1.1.3.md). La guía inicial sin anuncios no sirve para esta versión. La declaración realmente guardada en la consola todavía requiere comprobación.
2. **Preparar soporte:** confirmar que el buzón de soporte se atiende y verificar el recorrido completo de una solicitud de eliminación con una cuenta de prueba. Abrir la página no demuestra que la solicitud se haya atendido ni que se hayan eliminado los datos.
3. **Mantener la lista de pruebas físicas:** registrar resultado y versión instalada; no dar por probadas en el teléfono las correcciones que solo pasaron pruebas locales.

No hacen falta nuevos IDs publicitarios ni otra compilación para la preparación web. Azure, firma y subida Android siguen siendo manuales por el usuario.

## Pruebas físicas pendientes

| Prueba | Resultado esperado |
|---|---|
| Restaurar compras y Actualizar mi plan | Progreso y resultado visibles, incluido cuando no cambia el plan; error comprensible si no hay conexión. |
| Volver de una compra y desbloquear con biometría | Activación de Premium sin tener que restaurar manualmente. |
| Elegir equipo principal | Confirmación visible; selección conservada al volver a entrar. |
| Suscripción vencida | Free sin presentar la validez anterior como acceso vigente. |
| Oferta anual inicial | Primer año USD 19,99 de referencia para una cuenta elegible; renovación anual USD 24,99 de referencia, con precio local y condiciones de Play. |
| Banner e intersticial de prueba | Respeto de frecuencia y vistas; sin interrumpir órdenes, formularios o desbloqueo. |
| Video voluntario y SSV real | Tras ver y verificar el video, 30 minutos sin anuncios en app/web; conserva los límites Free. Cerrar antes o un callback inválido no concede recompensa. |
| Premium y pausa publicitaria | No se solicitan nuevos anuncios; vuelven únicamente cuando corresponda a Free sin pausa. |
| Consentimiento real web | Rechazo, preferencias, exclusión estadounidense y GPC bloquean solicitudes; Premium no carga la etiqueta publicitaria. Pendiente aprobación y activación limitada. |
| Casos especiales de Billing | Compra pendiente, gracia, retención por pago, revocación y cambio de cuenta; una compra no se atribuye a otra cuenta WoL. |

Las pruebas locales anteriores respaldan la implementación; no sustituyen estas pruebas con Google y el teléfono. Los datos personales de la cuenta facilitada a los revisores pueden modificarse durante su revisión; el usuario decidió continuar usando esa cuenta.

## Temas para una fase posterior

Producción pública y ampliación de anuncios a todas las cuentas Free, una vez superadas las verificaciones. Firma digital del instalador Windows e implementación para Apple son trabajos separados; no se han completado en esta fase.
