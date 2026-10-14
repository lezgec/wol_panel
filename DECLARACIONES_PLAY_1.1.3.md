# Declaraciones para Google Play: WoL Pro 1.1.3

Guía preparada el 10 de octubre de 2026. No se ha cambiado ni enviado ningún formulario de Play Console durante esta revisión. Comprobar primero la declaración actualmente guardada: la nota inicial de la versión 1.0.1 no refleja la publicidad ni las suscripciones actuales.

## Anuncios y permiso publicitario

- La versión 1.1.3 incluye banner, intersticial y video recompensado de AdMob para Free; Premium no muestra anuncios. La declaración de contenido con anuncios debe reflejar esa capacidad, aunque el alcance del servidor esté limitado durante la prueba.
- El manifiesto local incluye `com.google.android.gms.permission.AD_ID` y el App ID de AdMob. No reutilizar el antiguo «ID publicitario: No» sin contrastarlo con el AAB subido y el formulario vigente.
- El SDK solicita consentimiento antes de inicializar publicidad y pide anuncios no personalizados. Esto no significa ausencia de recopilación de datos publicitarios.

## Tipos de datos que revisar en Seguridad de datos

El formulario debe cubrir las versiones y regiones distribuidas que correspondan, incluyendo SDK y las páginas propias abiertas en la WebView. Una función opcional también puede requerir divulgación. No añadir datos que WoL Pro no recibe, como tarjetas bancarias o huellas.

| Tipo del formulario | Evidencia / uso actual | Recopilación y transferencia que revisar |
|---|---|---|
| Correo electrónico e ID de usuario | Cuenta, autenticación, recuperación y gestión | Recopilados por WoL. No se envía el correo a AdMob desde nuestro código. Billing utiliza un identificador de cuenta ofuscado. Evaluar transferencias por su finalidad y las excepciones del formulario. |
| Dispositivo u otros IDs | MAC del PC, agente/sesión; SDK publicitario con AD_ID y otros IDs | Recopilados por WoL para función/seguridad. AdMob recopila y comparte sus identificadores para publicidad, medición y prevención de fraude. |
| Interacciones en la app | Órdenes/resultados guardados en el historial; interacciones publicitarias del SDK | Recopilados. El historial propio no es efímero. AdMob comparte sus interacciones publicitarias; revisar las finalidades conjuntamente para este tipo. |
| Otro contenido generado por usuarios | Nombres de equipos y acciones | Recopilado para funciones; no se transmite como contenido publicitario desde nuestro código. |
| Apps instaladas | Catálogo de aplicaciones autorizadas del PC | Revisar la categoría por el catálogo transmitido; no es un escaneo de las aplicaciones del teléfono Android. |
| Historial de compras | Producto, estado, comprobante, vencimiento y pedido verificados en el servidor | Recopilado para acceso al plan, cuenta y validación de compras. WoL Pro no recibe el número de tarjeta. |
| Ubicación aproximada | El SDK puede inferir la ubicación general a partir de la IP | Revisar recopilación/compartición publicitaria conforme a la guía de Google; la ausencia de permisos GPS no descarta esta categoría. |
| Diagnósticos | Información de rendimiento recogida por Google Mobile Ads | Revisar recopilados/compartidos y finalidades del SDK. No seleccionar registros de fallos u otros tipos solo por suponer que todo SDK los recoge. |

La documentación de Google Mobile Ads informa de IP, interacciones, diagnósticos e identificadores para publicidad, análisis y prevención de fraude, y de cifrado TLS. La documentación consultada describe el SDK 25.5.0; la dependencia instalada declara 25.4.0. Antes de enviar el formulario, contrastar el SDK resuelto del AAB y cualquier mediación adicional. Esta guía identifica categorías a revisar; no sustituye la verificación de la declaración guardada.

## Uso y manejo

- Correo, ID de cuenta, equipos e historial persistente: no se procesan únicamente en memoria. El antiguo marcado de historial como efímero debe revisarse.
- La recopilación necesaria para iniciar sesión y prestar el servicio no se vuelve opcional por poder desinstalar la app. Las compras, el catálogo del agente y los datos de publicidad necesitan respuestas específicas según el recorrido y las opciones reales.
- No marcar todos los datos como compartidos de forma indiscriminada. Separar alojamiento/proveedores, transferencias iniciadas al vincular Alexa, verificación de compras y uso publicitario de Google.
- Revisar HTTPS y cifrado en tránsito para app, SDK y páginas propias. El código actual solicita anuncios no personalizados; no describirlo como seguimiento para personalización sin evidencia.
- No declarar borrado automático en 90 días, auditoría de seguridad independiente ni insignias que no estén implementadas o acreditadas.

## Eliminación y acceso de revisión

- URL pública de solicitud: `https://wol.luiszamora.dev/account-deletion`.
- El usuario confirmó que abre desde la app. La eliminación requiere atención del soporte; sigue pendiente probar la atención y eliminación completa con una cuenta de prueba.
- La eliminación de WoL Pro no cancela automáticamente la suscripción de Google Play; las instrucciones de soporte deben recordarlo.
- La cuenta personal fue facilitada a los revisores por decisión del usuario. No declarar acceso sin restricciones ni inventar una cuenta de demostración o un PC simulado que no existen.

## Ficha de tienda

La descripción debe explicar Free (un equipo activo, Alexa y apagado protegido) y Premium (hasta diez equipos activos, aplicaciones y comandos autorizados, sin anuncios). Los precios localizados, elegibilidad y renovación se muestran en Google Play. El video voluntario pausa publicidad durante 30 minutos sin activar Premium. No anunciar encendido por router ni afirmar disponibilidad pública mundial mientras producción siga pendiente.

## Fuentes oficiales y evidencia local

- [Divulgación de Google Mobile Ads](https://developers.google.com/admob/android/privacy/play-data-disclosure).
- [Formulario de Seguridad de datos](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en).
- Evidencia: `wol-pro-app/package.json`, `android/app/src/main/AndroidManifest.xml`, `src/mobileAds.tsx`, `src/mobileApi.ts`, dependencia `react-native-google-mobile-ads`; backend `billing.py`, `templates/privacy.html` y `templates/account_deletion.html`.

Siguiente paso: comparar esta guía con los formularios guardados en Play Console y corregir discrepancias reales. No retirar la versión en revisión ni generar un AAB nuevo solo para actualizar texto o declaraciones.
