# Cuentas publicitarias WoL Pro — 10 de octubre de 2026

## Estado vigente: tres formatos en Android 1.1.3 / código 5

La configuración local está en live con las tres unidades reales. pixel9 y a115 figuran como dispositivos de prueba en AdMob. No se guardó el ID privado del teléfono en documentos o repositorios. El usuario ya subió Android 1.1.3 / código 5 a prueba cerrada y está en revisión; no hay que repetir la compilación por estas notas. Las pruebas físicas de los tres formatos y de la recompensa siguen pendientes.

`ADS_TEST_USER_IDS` limita los formatos Android a las cuentas configuradas, respetando los interruptores administrativos. La recompensa de prueba es de treinta minutos. La preparación web posterior usa `ADS_WEB_READY` y `ADS_WEB_TEST_USER_IDS` de forma independiente. No concede Premium ni omite comprobaciones de suspensión, pausa o firma SSV. Un alcance mal formado bloquea la publicidad correspondiente; vacío conserva la política administrativa normal.

El usuario instaló `artifacts/ads-setup/WoLPro-all-ads-1.1.3.zip` en Azure y después `WoLPro-web-ads-1.1.3.zip`. Backend y administrador actualizados, servicio activo. Se conservan banner, intersticial y video Android limitados a la cuenta interna 1, y la web preparada sin activar. Los pasos anteriores de instalación se conservan como referencia; no repetirlos. Estado y pruebas pendientes: [PENDIENTES_PUBLICACION.md](PENDIENTES_PUBLICACION.md).

En AdMob se verificaron las tres unidades, actualización de banner optimizada por Google y límite intersticial de una impresión cada diez minutos. Se guardó Anuncios con alta participación desactivado para evitar pasos y tiempos adicionales. El cierre lo controla Google. Referencia: https://support.google.com/admob/answer/15525707.

En la última consulta de AdMob la aplicación mostró Debe revisarse, sin ficha pública de tienda vinculada; Añadir estaba deshabilitado. La aprobación para anuncios reales y la prueba SSV desde el teléfono siguen pendientes. El usuario subió la versión a revisión cerrada en Play Console.

Cuenta elegida por el titular: `zamgarluer@gmail.com`. AdMob y AdSense comparten
el publicador `pub-8703217786138724`, Ecuador, USD. AdSense se conectó a la cuenta
ya creada por AdMob, sin abrir una segunda cuenta de publicador.

## Android: unidades creadas

| Configuración | Identificador público |
| --- | --- |
| App ID | `ca-app-pub-8703217786138724~9066626717` |
| Banner superior | `ca-app-pub-8703217786138724/7753545047` |
| Intersticial | `ca-app-pub-8703217786138724/9595083634` |
| Video voluntario, 30 minutos sin anuncios | `ca-app-pub-8703217786138724/3375316331` |

El intersticial tiene además una cuota en AdMob de una impresión por usuario
cada diez minutos. La cuota de tres al día y las restricciones por cuenta siguen
aplicándose en el backend. El recompensado concede 30 `minutos sin anuncios`;
se desactivaron anuncios interactivos y grupos de anuncios en esa unidad.

La app figura como Android todavía no publicada en una tienda compatible.
Vincularla a `dev.luiszamora.wolpro` cuando la ficha pública de Google Play
esté disponible; el enlace de incorporación a prueba interna no es una ficha pública.
No se creó una app iOS de AdMob: se hará al preparar la distribución para Apple.

Los IDs quedaron en `.env.example` y en el `.env` local de `wol-pro-app`,
con `.env.example` en modo off seguro y el `.env` local en live; ambas configuraciones usan `EXPO_PUBLIC_ADS_PLATFORMS=android`.
Esto permite habilitar Android cuando esté listo, sin exigir IDs de la futura
versión iOS ni inicializar anuncios reales en esa plataforma.

## Web: unidades creadas

| Configuración | Valor |
| --- | --- |
| `ADSENSE_CLIENT` | `ca-pub-8703217786138724` |
| `ADSENSE_BANNER_SLOT` | `7179749843` |
| `ADSENSE_RECTANGLE_SLOT` | `9557581305` |

El sitio registrado es `luiszamora.dev`: Google rechazó el alta inicial usando
solo `wol.luiszamora.dev` y exigió el dominio principal. La ficha requiere
verificación de propiedad y revisión. Los anuncios automáticos estaban desactivados;
se crearon unidades manuales para respetar Premium y la pausa de publicidad.

## Archivos para publicar manualmente

Los archivos `ads.txt` y `app-ads.txt` contienen el fragmento personalizado
mostrado por Google:

```text
google.com, pub-8703217786138724, DIRECT, f08c47fec0942fa0
```

El backend actualizado sirve `/ads.txt` y `/app-ads.txt` públicamente, como texto
plano, sin iniciar sesión. Copia los dos archivos junto con el código actualizado
de este repositorio a Azure y reinicia el servicio según `MONETIZATION_DEPLOYMENT.md`.
No sobrescribas tu `.env`, claves, base de datos ni carpeta de estado.

**El dominio principal tiene un sitio distinto, el portafolio.** Actualizar el
backend de WoL no publica automáticamente estos archivos en `luiszamora.dev`.
Sube también `ads.txt` a la raíz pública del alojamiento del portafolio para que
abra `https://luiszamora.dev/ads.txt`. Si ya existe, añade la línea conservando
los vendedores existentes. Después podrás marcar «Publiqué el archivo ads.txt»,
verificar en AdSense y solicitar revisión del sitio. No se marcó como publicado.

Para AdMob, configura como web de contacto de la ficha de Play
`https://wol.luiszamora.dev`, y comprueba el archivo en
`https://wol.luiszamora.dev/app-ads.txt`. Google lo rastrea a partir de la web
de desarrollador de la ficha. No se cambió la ficha de Play en esta configuración.

## Historial de preparación y diagnóstico SSV

Las notas cronológicas siguientes documentan problemas ya corregidos. El callback de consola está verificado y guardado; no reinstalar las correcciones antiguas. Sigue pendiente la recompensa real desde Android.

La URL de verificación por servidor es
`https://wol.luiszamora.dev/api/ads/ssv`. En la primera configuración devolvía
404, por lo que no se guardó ni verificó esa URL en AdMob.

Después del despliegue, una nueva comprobación pública del 10 de octubre
confirmó `/ads.txt` y `/app-ads.txt` del subdominio WoL con HTTP 200 y la línea
del publicador correcto. El endpoint `/api/ads/ssv` ya existe: sin parámetros
devolvió HTTP 409, `ads_disabled`, «Recompensas todavía no configuradas»; el
verificador devuelve ese resultado cuando falta `ADMOB_REWARDED_UNIT` en el
entorno del servicio. No se envió un callback firmado ni se acreditó recompensa.
`https://luiszamora.dev/ads.txt` sigue devolviendo 404: aún falta publicar el
archivo en el dominio principal del portafolio. Las recompensas reales siguen
pendientes de configuración y prueba.

Al revisar el portafolio Astro `lezgec/porfolio-luiszamora.dev`, el archivo estaba
en `src/pages/ads.txt`: el build no lo publica como página. Se movió en la copia
local a `public/ads.txt`; `npm run build` con Node 24 terminó sin diagnósticos
y generó `dist/ads.txt` con contenido idéntico. Falta que el usuario suba este
cambio a GitHub para que el workflow de `main` lo publique; no se ejecutó push
ni un despliegue desde esta revisión.

El usuario publicó la corrección y la comprobación posterior confirmó
`https://luiszamora.dev/ads.txt` con HTTP 200, `text/plain; charset=utf-8` y la
línea exacta `google.com, pub-8703217786138724, DIRECT, f08c47fec0942fa0`.
La publicación del archivo está comprobada; la verificación y revisión del
sitio en AdSense todavía requieren comprobar el estado en la cuenta de Google.

En el entorno de Azure añade los valores públicos de `.env.production.example`:

```dotenv
ADS_LIVE_READY=0
ADMOB_REWARDED_UNIT=ca-app-pub-8703217786138724/3375316331
ADSENSE_CLIENT=ca-pub-8703217786138724
ADSENSE_BANNER_SLOT=7179749843
ADSENSE_RECTANGLE_SLOT=9557581305
```

Google envía `ad_unit=3375316331` en el callback; el verificador ahora acepta
configurar el ID numérico o el ID completo, pero comprueba el sufijo exacto,
la firma ECDSA original, la antigüedad y el ticket emitido por WoL Pro.
Un callback sin ticket válido no acredita minutos. Para la herramienta de
AdMob se añadió el valor reservado `wolpro-ssv-console-check` en `custom_data`:
se verifican firma, unidad y antigüedad como siempre, pero responde HTTP 200
con `diagnostic=true` y `reward_granted=false`, sin escribir en ninguna cuenta.
Los demás valores siguen requiriendo un ticket real. Este ajuste aún debe
copiarse manualmente a Azure antes de verificar la URL en AdMob.

Falta completar el perfil de pagos y la revisión de Google, configurar los
mensajes de consentimiento UMP de la app y el CMP certificado de la web,
verificar SSV con Azure actualizado y probar la recompensa desde un dispositivo.
Después se puede pasar la app a `live`, regenerar Android conservando la clave
de carga, firmar un nuevo AAB y actualizar las declaraciones de Play.
Finalmente, habilitar `ADS_LIVE_READY=1` y los formatos desde el administrador.

Referencias: [app-ads.txt](https://support.google.com/admob/answer/9363762),
[ads.txt](https://support.google.com/adsense/answer/12171612),
[verificación de recompensas](https://developers.google.com/admob/android/ssv).

## Avance confirmado del 10 de octubre: Azure y consentimiento

El usuario guardó `ADMOB_REWARDED_UNIT` en Azure, conservó
`ADS_LIVE_READY=0` y reinició `wol.service`, que quedó activo. Respaldo:
`/var/backups/wol-pro/ads-config-6on5wbve`. El endpoint SSV sin firma pasó
a responder HTTP 403 `invalid_signature`, el rechazo esperado de una petición
sin firma. Esto no demuestra todavía la recepción de una recompensa firmada.

La consola de AdMob mostró la cuenta aprobada y el perfil de pagos completo;
la app sigue pendiente de vincularse a la tienda para su revisión. AdSense
también mostró el perfil completo, pero aún pide conectar el sitio.

Se publicó en AdMob `WoL Pro - Consentimiento europeo`, asociado a la app
Android existente, con inglés y las 31 traducciones adicionales ofrecidas por
Google, opciones para consentir, administrar preferencias y no consentir.
Se añadió `https://wol.luiszamora.dev/privacy`, comprobada con HTTP 200.
La consola confirmó estado `Publicado`. Captura local:
`artifacts/ads-setup/admob-consentimiento-europeo.png`.

También se publicó `WoL Pro - Privacidad Estados Unidos` para WoL Pro,
en inglés (en-US), español (es) y español latinoamericano (es-419), con opción
de rechazar la venta o compartición y alcance a los estados actuales y futuros
admitidos por Google. Captura: `artifacts/ads-setup/admob-privacidad-eeuu.png`.

En AdSense se seleccionó la verificación por ads.txt, Google confirmó
`Tu sitio está verificado` y se solicitó revisión. La pantalla final mostró
`Gracias por conectar el sitio` y los pasos completados. No equivale a la
aprobación del sitio. Captura: `artifacts/ads-setup/adsense-sitio-conectado.png`.

Publicar los mensajes no activa los anuncios de la app ni del servidor. Siguen
pendientes CMP web y la prueba firmada de SSV. `python -m unittest
test_monetization -q` pasó 18 pruebas, incluida la verificación diagnóstica sin
recompensa, rechazos de firma/unidad/antigüedad y la recompensa normal de 30
minutos. Se fijó el reloj al mediodía en el test del límite diario para evitar
que sus impresiones simuladas pasaran al día UTC anterior cerca de medianoche.

El usuario instaló el ajuste SSV en Azure: SHA-256 validado, sintaxis correcta,
`SSV_INSTALADO_OK`, servicio activo y respaldo en
`/var/backups/wol-pro/admob-ssv-h1kInL`. Se intentó verificar la URL en AdMob
con `custom_data=wolpro-ssv-console-check`; Google informó HTTP 403. La URL
no se guardó como verificada. Pendiente revisar los parámetros del callback
real para diagnosticar el rechazo, sin quitar las comprobaciones de firma.

El usuario confirmó el formato Nginx `wol_safe`, basado en `$uri`: las dos
peticiones SSV con HTTP 403 no incluyen sus parámetros en el registro. Esto
no demuestra que Google los enviara vacíos. Se preparó un ajuste local que
registra la etapa de rechazo, identificador público de unidad, antigüedad,
ID de clave y estado de descarga de claves, sin firma, tickets, transacción
ni datos de usuario. Todas las validaciones permanecen activas. Pasaron 19
pruebas, incluida la ausencia de datos privados en esos registros.

Archivo de despliegue manual:
`artifacts/ads-setup/WoLPro-ads-verification-diagnostic.py`.
SHA-256: `b8ce54d8bafbaa7a98a695f327d51d649ee76efa74cb58d81ae5e7d6e64ae5e9`.
El usuario confirmó la instalación del diagnóstico. Se repitió la prueba
en AdMob con el marcador reservado y Google volvió a informar HTTP 403.
Pendiente leer `journalctl -u wol.service` para identificar la etapa exacta
del rechazo. La URL sigue sin verificarse ni guardarse.

El registro del servidor identificó `stage=ad_unit unit=1234567890` con
`console_check=True`: la consola envía una unidad ficticia en su prueba.
Se admite esa unidad únicamente con el marcador reservado; la firma de Google
y la antigüedad siguen siendo obligatorias, y el diagnóstico no concede
recompensas. Un ticket normal con la unidad ficticia sigue rechazándose.
Pasaron las 19 pruebas, ampliadas con firma adulterada, clave desconocida,
antigüedad y prohibición de recompensa con la unidad ficticia.

Nuevo archivo para instalación manual:
`artifacts/ads-setup/WoLPro-ads-verification-console-fix.py`.
SHA-256: `7b1f3e621d354f2f6c1d4daf69bb9e283b5a05e6147460bd82c10034f9ad0a95`.
Instalador: `artifacts/ads-setup/install-ssv-console-fix.sh`, con validación
de SHA-256 y sintaxis, respaldo y restauración si falla el reinicio.
El usuario confirmó la instalación de la corrección. Se repitió la prueba
de la consola, que todavía informó HTTP 403. Pendiente leer la nueva etapa
de rechazo en el diagnóstico; la URL aún no se ha guardado como verificada.

La prueba real siguiente llegó a `stage=signature`, con `key_http=200`
y `InvalidSignature`. Se revisaron el ejemplo oficial de Google y el código
de Tink: utilizan `URI.getQuery()` (decodificación porcentual una sola vez,
conservando orden y los signos `+` literales), mientras nuestra implementación
validaba los bytes codificados. Se ajustó la representación firmada conforme
a esa referencia; la firma ECDSA sigue siendo obligatoria. Se rechazan escapes
inválidos y delimitadores de parámetros codificados para evitar ambigüedad.

Referencias:
- https://developers.google.com/admob/android/ssv#get_content_to_be_verified
- https://github.com/tink-crypto/tink-java-apps/blob/main/rewardedads/src/main/java/com/google/crypto/tink/apps/rewardedads/RewardedAdsVerifier.java

Pasaron 20 pruebas, con espacios, UTF-8, `+` literal, porcentajes, firma
escapada y manipulación de campos. El diagnóstico con recompensa en español
no concede minutos; el ticket real verificado concede los 30 minutos de Free.
La corrección todavía requiere confirmar el callback real en Azure.

Archivo: `artifacts/ads-setup/WoLPro-ads-verification-signature-fix.py`.
SHA-256: `c07ef10dd7a595161b6a893c530c696c68b38e22d6a50511614b6f9ba70288ae`.
Instalador manual: `artifacts/ads-setup/install-ssv-signature-fix.sh`.
El usuario confirmó la instalación. Al retomar AdMob, la consola mostró
`Listo. Se verificó su URL de devolución de llamada.` Se pulsó `Usar la URL
verificada` y `Guardar`; tras completar la carga, se reabrió la sección y
se comprobó la URL guardada `https://wol.luiszamora.dev/api/ads/ssv`.
La unidad recompensada `3375316331` conserva la recompensa de 30 minutos.
Capturas: `artifacts/ads-setup/admob-ssv-verificada.png` y
`artifacts/ads-setup/admob-ssv-guardada.png`.

SSV de consola configurado y verificado. La prueba fue diagnóstica y no
concedió recompensas. Siguen pendientes la prueba desde Android de recompensa
real, CMP web y aprobación/vinculación de la app y del sitio según corresponda.
Los anuncios siguen desactivados en los clientes y en la configuración de Azure.

## Estado actualizado: preparación web y tres formatos Android

El usuario desplegó `WoLPro-all-ads-1.1.3.zip` en Azure: banner, intersticial y recompensa limitados a la cuenta 1, servicio activo. Android 1.1.3 está en revisión. Este estado sustituye la nota anterior de desactivación total.

Para la web se publicaron en AdSense **WoL Pro web - Consentimiento europeo** (inglés y 31 traducciones, rechazar habilitado, optimización del mensaje desactivada) y **WoL Pro web - Privacidad Estados Unidos** (inglés y dos variantes españolas, todos los estados actuales/futuros). Los dos mensajes figuran Publicados. Se comprobaron las unidades banner `7179749843` y rectángulo `9557581305`. Anuncios automáticos y optimización automática quedaron desactivados.

La implementación web usa el CMP de Google y espera decisiones regionales válidas antes de solicitar espacios, con anuncios no personalizados. Premium, recompensa vigente, rechazo y GPC bloquean los espacios. El nuevo `ADS_WEB_READY` y alcance `ADS_WEB_TEST_USER_IDS` son independientes del alcance Android. El administrador indica la preparación web.

El usuario confirmó la instalación manual de `artifacts/ads-setup/WoLPro-web-ads-1.1.3.zip`: `WEB_ADS_PREPARADA_SIN_ACTIVAR` y servicio activo. El instalador dejó `ADS_WEB_READY=0`, conservó la política Android y no modificó bases. La última consulta de AdSense mostró **Preparando el sitio** y **ads.txt: Autorizado**. Faltan la aprobación y la comprobación real del CMP/inventario con alcance limitado; no falta el despliegue ni requiere otra compilación Android. Pasos y límites en `WEB_ADS_DEPLOYMENT.md`.

Evidencias: `artifacts/ads-setup/adsense-web-privacidad-lista.png`, `adsense-web-consentimiento-europeo.png`, `adsense-web-privacidad-eeuu.png`, `adsense-web-solo-unidades-manuales.png`.
