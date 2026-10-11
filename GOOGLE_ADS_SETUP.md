# Cuentas publicitarias WoL Pro — 10 de octubre de 2026

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
con `EXPO_PUBLIC_ADS_MODE=off` y `EXPO_PUBLIC_ADS_PLATFORMS=android`.
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

## Recompensa y activación: pendiente del despliegue

La URL de verificación por servidor es
`https://wol.luiszamora.dev/api/ads/ssv`. La comprobación pública actual devolvió
404: Azure todavía no tiene este endpoint. Por eso no se guardó ni verificó
esa URL en AdMob y no se activaron las recompensas reales.

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
Un callback sin ticket válido no acredita minutos. La verificación de la URL
con la herramienta de AdMob requiere coordinar un ticket válido del servidor
en el entorno de prueba; no simular premios ni desactivar la firma en producción.

Falta completar el perfil de pagos y la revisión de Google, configurar los
mensajes de consentimiento UMP de la app y el CMP certificado de la web,
verificar SSV con Azure actualizado y probar la recompensa desde un dispositivo.
Después se puede pasar la app a `live`, regenerar Android conservando la clave
de carga, firmar un nuevo AAB y actualizar las declaraciones de Play.
Finalmente, habilitar `ADS_LIVE_READY=1` y los formatos desde el administrador.

Referencias: [app-ads.txt](https://support.google.com/admob/answer/9363762),
[ads.txt](https://support.google.com/adsense/answer/12171612),
[verificación de recompensas](https://developers.google.com/admob/android/ssv).
