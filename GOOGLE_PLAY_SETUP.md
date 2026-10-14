# Google Play Billing — configuración real

Estado revisado el 10 de octubre de 2026. Azure se actualiza manualmente.

Estado vigente: configuración Billing instalada y comprobada en Azure, RTDN de prueba recibido con HTTP 200 y reconciliación cada quince minutos activa. El usuario confirmó compras mensual/anual y cancelación hasta el regreso a Free. Android 1.1.3 está en revisión cerrada. Las instrucciones de credenciales, RTDN y temporizador siguientes conservan el historial de preparación; no hay que repetirlas. Los casos físicos todavía pendientes están en [PENDIENTES_PUBLICACION.md](PENDIENTES_PUBLICACION.md).

## Catálogo y distribución

Paquete Android: `dev.luiszamora.wolpro`. Suscripción: `wolpro_premium`.

| Plan / oferta | Referencia en USD | Renovación | Disponibilidad guardada |
| --- | --- | --- | --- |
| `monthly` | 2,99 al mes | Mensual automática | 175 mercados compatibles |
| `annual` | 24,99 al año | Anual automática | 175 mercados compatibles |
| `intro-year`, etiqueta `intro-year` | 19,99 el primer año | Después, el precio local del plan anual | 175 mercados compatibles |

Los tres aparecen **activos** en Play Console. La oferta tiene una fase de
**pago único de un año**, seguida de la renovación anual normal. La elegibilidad
en Google es adquisición de clientes que no tuvieron esta suscripción. WoL Pro
también comprueba su política de promoción; Google determina la oferta final
disponible para la cuenta de tienda.

Se aplicaron conversiones de Google para todos los mercados y precios de
respaldo para otras regiones. No se cobra el mismo número en todas las monedas:
la app muestra el precio y las fases devueltos por Google Play. Los USD son
referencias; revisar cualquier cambio posterior de precios antes de guardarlo.

La prueba cerrada **Alpha** se amplió de Ecuador a **178 países y regiones**,
incluido Resto del mundo. Ese cambio quedó guardado para enviarlo a revisión.
Esto no publica la app en producción. Al habilitar producción, comprobar allí
la cobertura geográfica, los requisitos de prueba y la aprobación de Google.

## Proyecto e identidades

- Proyecto: **WoL Pro Billing**, ID `wolpro-billing-20261010`.
- Número de proyecto: `256569134336`.
- APIs habilitadas: Google Play Android Developer API y Cloud Pub/Sub API.
- Billing: `wolpro-play-billing@wolpro-billing-20261010.iam.gserviceaccount.com`.
  En Play Console aparece activo, con acceso solo a WoL Pro: lectura de la app
  (incluye calidad), datos financieros y administración de pedidos/suscripciones.
  Sin permisos de administrador, publicación ni acceso a otras apps.
- Push: `wolpro-rtdn-push@wolpro-billing-20261010.iam.gserviceaccount.com`.
  Sin clave JSON ni permisos de Play. Pub/Sub firma con esta identidad.

Tema: `projects/wolpro-billing-20261010/topics/wolpro-rtdn`.
Google Play tiene el rol Publicador de Pub/Sub sobre ese tema.
Receptor: `projects/wolpro-billing-20261010/subscriptions/wolpro-rtdn-azure`.
Entrega autenticada por HTTPS con envoltura JSON; no separar la carga útil.

Endpoint y audiencia (idénticos):
`https://wol.luiszamora.dev/api/billing/google/rtdn`.
Identidad OIDC: la cuenta push anterior. Sin vencimiento por inactividad,
confirmación de 30 segundos, reintentos exponenciales de 10 a 600 segundos.
El agente de Pub/Sub
`service-256569134336@gcp-sa-pubsub.iam.gserviceaccount.com` requiere el rol
Creador de tokens de cuenta de servicio sobre **la cuenta push**, no sobre
todas las cuentas del proyecto.

Ese rol quedó concedido sobre la cuenta push y se verificó como asignación
sin herencia. RTDN quedó habilitado y guardado en Play Console con el tema
anterior. El usuario instaló la clave y configuró Azure manualmente; la
comprobación terminó con `BILLING_CONFIG_OK`. Tras solicitar notificaciones de
prueba, las métricas de la suscripción muestran la serie `push_request_count
ack_200` con actividad: el endpoint respondió HTTP 200. El registro de Azure
`/var/log/nginx/wol-access.log` confirmó dos POST con respuesta 200 el 10 de
octubre de 2026 a las 22:18:43 y 22:20:20 UTC. La entrega de prueba está
verificada; falta comprobar una compra de prueba y activar la reconciliación.

## Pendiente: clave privada y Azure

Crear personalmente una clave **JSON** de la cuenta **Billing** en Google Cloud:
Cuentas de servicio → WoL Pro Play Billing → Claves → Agregar clave → Crear clave
nueva → JSON. No crear una clave para la cuenta push. No pegar el JSON en chats,
no incluirlo en el repositorio y no usar variables `EXPO_PUBLIC_*` para secretos.

En PowerShell, ajustar solamente el archivo descargado y el destino SSH habitual:

```powershell
$wolBillingJson = 'C:\Users\lezgo\Downloads\NOMBRE-DEL-ARCHIVO.json'
$wolAzureHost = 'HOST-O-IP-DE-TU-AZURE'
scp $wolBillingJson "azureuser@${wolAzureHost}:/home/azureuser/wolpro-google-play.json"
```

En Azure, instalar la clave con acceso del servicio `wol`. No imprimir su contenido:

```bash
sudo install -d -o wol -g wol -m 700 /var/lib/wol-pro/credentials
sudo install -o wol -g wol -m 600 \
  /home/azureuser/wolpro-google-play.json \
  /var/lib/wol-pro/credentials/google-play-service.json

sudo -u wol /srv/apps/wakeonlan/.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('/var/lib/wol-pro/credentials/google-play-service.json')
c = json.loads(p.read_text())
assert c['type'] == 'service_account'
assert c['project_id'] == 'wolpro-billing-20261010'
assert c['client_email'] == 'wolpro-play-billing@wolpro-billing-20261010.iam.gserviceaccount.com'
assert c.get('private_key')
print('CLAVE_BILLING_OK')
PY
```

Respaldar `.env` antes de editarlo. Este paso habilita compras al reiniciar el
servicio; ejecutarlo después de revisar credencial, permisos, receptor y cuenta
de prueba de licencia. Conservar cualquier `BILLING_ACCOUNT_SECRET` existente:
cambiarla rompe la asociación de recibos con las cuentas WoL Pro.

```bash
sudo /srv/apps/wakeonlan/.venv/bin/python - <<'PY'
import os, secrets, shutil, tempfile
from pathlib import Path
from dotenv import dotenv_values, set_key

base = Path('/srv/apps/wakeonlan')
env = base / '.env'
assert env.is_file()
os.umask(0o077)
backup_root = Path('/var/backups/wol-pro')
backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
backup = Path(tempfile.mkdtemp(prefix='billing-', dir=backup_root))
shutil.copy2(env, backup / 'env-backup')
os.chmod(backup / 'env-backup', 0o600)
values = dotenv_values(env)
settings = {
    'GOOGLE_PLAY_PACKAGE': 'dev.luiszamora.wolpro',
    'GOOGLE_PLAY_PRODUCTS': 'wolpro_premium',
    'GOOGLE_PLAY_CREDENTIALS': '/var/lib/wol-pro/credentials/google-play-service.json',
    'BILLING_ACCOUNT_SECRET': values.get('BILLING_ACCOUNT_SECRET') or secrets.token_urlsafe(48),
    'GOOGLE_RTDN_AUDIENCE': 'https://wol.luiszamora.dev/api/billing/google/rtdn',
    'GOOGLE_RTDN_SERVICE_EMAIL': 'wolpro-rtdn-push@wolpro-billing-20261010.iam.gserviceaccount.com',
}
original = env.stat()
for name, value in settings.items():
    set_key(str(env), name, value, quote_mode='always')
os.chown(env, original.st_uid, original.st_gid)
os.chmod(env, original.st_mode & 0o777)
print('CONFIG_BILLING_GUARDADA')
print('RESPALDO=' + str(backup))
PY

sudo systemctl restart wol.service
sudo systemctl is-active wol.service
```

La importación de `app` carga `.env`, igual que la aplicación. Verificar sin
imprimir claves ni tokens:

```bash
cd /srv/apps/wakeonlan

sudo -u wol /srv/apps/wakeonlan/.venv/bin/python - <<'PY'
from app import billing
assert billing.enabled, 'Faltan variables de Billing'
print('BILLING_CONFIG_OK')
PY
```

Esto comprueba configuración, **no** valida una compra real. Después de verificar
la copia privada instalada, retirar la copia temporal de la clave en
`/home/azureuser`; guardar un respaldo privado conforme a la política del servidor.

## Comprobación de notificaciones y compras

En Play Console → WoL Pro → Configuración de la monetización, RTDN utiliza el
tema anterior y contenido Solo suscripciones y compras anuladas. Tras configurar
Azure, enviar el mensaje de prueba. Comprobar dos cosas distintas: publicación
correcta en Google y respuesta **200** de Azure en Nginx. El endpoint devuelve
`ignored` para la notificación de prueba; no concede Premium.

```bash
sudo grep -F '/api/billing/google/rtdn' /var/log/nginx/wol-access.log | tail -n 10
sudo journalctl -u wol.service --since '10 minutes ago' --no-pager
```

Si el log anterior no muestra peticiones, el sitio puede usar otro archivo o tener
el registro desactivado. Buscar en los logs actuales e inspeccionar solamente
las directivas de registro y los nombres de sitios, sin volcar toda la
configuración de Nginx:

```bash
sudo grep -H -F '/api/billing/google/rtdn' /var/log/nginx/*.log | tail -n 15
sudo nginx -T 2>/dev/null | grep -nE 'configuration file|server_name|access_log'
```

La serie `ack_200` en Pub/Sub confirma respuestas HTTP 200 del endpoint, pero
no verifica un recibo de compra. Las pruebas de compras indicadas abajo siguen
siendo necesarias.

Antes de comprar, añadir el correo de prueba como **verificador de licencia** en
Play Console y usar esa misma cuenta en Google Play del teléfono. La cuenta de
WoL Pro puede ser distinta. Confirmar que el diálogo identifica una compra de
prueba antes de completarla. La cortesía Premium del propietario puede ocultar
un fallo de compra: usar una cuenta WoL Pro Free separada y comprobar que el
origen del acceso es Google Play.

La lista existente **Pruebas WoL Pro** (tres cuentas, incluida
`zamgarluer@gmail.com`) quedó seleccionada y guardada como verificadora de
licencias, con respuesta `RESPOND_NORMALLY`. Esta configuración es común a las
apps de la cuenta de desarrollador, no exclusiva del segmento Alpha. No se
realizó una compra ni se cambió el acceso de la cuenta WoL Pro por este ajuste.

Validar mensual, anual, primer año elegible, restauración, pago pendiente,
cancelación de renovación, vencimiento, revocación y cambio de cuenta. Un recibo
no debe vincularse a dos cuentas WoL Pro. Comprobar también web, Alexa y agente
contra el plan verificado. Guardar el precio local mostrado y la renovación
siguiente al revisar la oferta.

El 10 de octubre el usuario mostró el diálogo mensual con tarjeta de prueba
y, después, la pantalla Mi plan con Premium, hasta diez equipos, renovación
automática y vencimiento a las 17:32:26 de ese día. La activación se refleja
en la app. El usuario ejecutó después `billing_reconcile.py` en Azure y obtuvo
`{"checked": 1, "failed": 0}`: el backend pudo volver a verificar una
suscripción almacenada con Google Play sin errores. El usuario instaló después
el servicio y el timer: `Result=success`, `ExecMainStatus=0` y enlace de
activación creado. Respaldo: `/var/backups/wol-pro/billing-timer-gjkWbG`.
La comprobación posterior confirmó el timer `active`, próxima ejecución a
las 22:56:13 UTC y dos ejecuciones iniciales a las 22:41:08 y 22:41:09 UTC,
ambas con `{"checked": 1, "failed": 0}` y finalización correcta. La revisión
periódica quedó instalada y programada. Quedan pendientes las pruebas de
restauración, cancelación y vencimiento.

El usuario probó Restaurar compras y observó botones temporalmente bloqueados
sin mensaje final. La revisión del código móvil encontró que los caminos de
éxito, pago pendiente y acceso no vigente podían terminar sin información.
Se preparó la corrección móvil 1.1.2 / código Android 4 con progreso visible,
diálogo final, actualización del plan y siete pruebas de restauración. Las
31 pruebas móviles, TypeScript y lint pasaron. Falta generar y subir el AAB
firmado e instalarlo para repetir la prueba física. No requiere otro despliegue
del backend para esta corrección.

Una captura posterior del teléfono, a las 17:57, mostró Premium con acceso
hasta las 17:57:26 y renovación automática, frente a las 17:32:26 de la primera
captura. La app recibió una fecha de suscripción actualizada. Esta evidencia
no distingue qué actualización llegó por RTDN y cuál por reconciliación, ni
confirma aún cancelación o vencimiento.

Posteriormente el usuario canceló la suscripción desde Google Play y confirmó
que WoL Pro mostró primero Premium sin renovación automática. Al llegar la
fecha de acceso cambió a Free. El ciclo de cancelación y vencimiento quedó
comprobado en el teléfono. La versión instalada seguía mostrando la fecha
anterior en el texto de la suscripción; la corrección móvil preparada distingue
el estado vencido y no lo presenta como acceso vigente. Falta comprobar esa
presentación con el próximo AAB y los permisos de Free en el teléfono.
Estos resultados no dan por validado todo el ciclo de suscripción.

## Reconciliación periódica

`billing_reconcile.py` ya está incluido en el backend. Instalar las plantillas
de [deploy/systemd](deploy/systemd) y activar el timer tras configurar Billing:

```bash
sudo install -m 644 deploy/systemd/wol-billing-reconcile.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/wol-billing-reconcile.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wol-billing-reconcile.timer
sudo systemctl start wol-billing-reconcile.service
sudo journalctl -u wol-billing-reconcile.service -n 10 --no-pager
sudo systemctl list-timers wol-billing-reconcile.timer --no-pager
```

Ejecutar esos comandos desde `/srv/apps/wakeonlan`, después de copiar las
plantillas. Un resultado sin compras (`checked=0`) no prueba acceso a un recibo.
La reconciliación complementa RTDN y es necesaria para los eventos de compras
anuladas que el endpoint actual no procesa directamente. Mantener ambos.

Actualizar Seguridad de los datos y la política de privacidad para reflejar
historial de compras antes de publicar una versión con compras habilitadas.
La configuración mundial no implica aprobación pública ni disponibilidad de
Google Play Billing en países donde el servicio está restringido.

Referencias: [acceso a la API de Play](https://developers.google.com/android-publisher/getting_started),
[preparación de Billing y RTDN](https://developer.android.com/google/play/billing/getting-ready),
[autenticación push](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions),
[monedas y precios locales](https://support.google.com/googleplay/android-developer/answer/1169947?hl=en).
