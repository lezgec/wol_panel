# WoL Pro

Panel multiusuario Flask + Waitress, con MariaDB para cuentas/dispositivos/auditoría
y SQLite persistente para OAuth, desafíos de correo, límites, permisos y cola Alexa.
El despliegue principal es nativo en Ubuntu 24.04 con systemd, Nginx y Cloudflare.

- [Instalar en Azure: comandos SSH, MariaDB, systemd, Nginx y DNS](DEPLOY_AZURE.md).
- [Configurar y publicar la skill Alexa](ALEXA_SETUP.md).
- [Pruebas unitarias e integración MariaDB aislada](TESTING.md).

## Métodos de encendido

| Método | Datos | Cómo se usa |
| --- | --- | --- |
| Alexa / Echo | Nombre y MAC | Voz/app Alexa; Echo compatible en la LAN de la PC |
| Router por Internet | Nombre, MAC, IPv4 pública/DDNS y puerto UDP | Botón web o Alexa, router ya preparado para Wake-on-WAN |
| Local | Nombre y MAC | Backend en la misma LAN; deshabilitado en producción |

La app no configura routers. WoL requiere hardware preparado y alimentación;
UDP enviado no confirma el arranque. El botón web de un equipo Echo muestra las
instrucciones de Alexa: no inventa su `correlationToken`. No se implementa apagado.
El login con Amazon permanece oculto; vincular la skill es independiente del login web.

## Desarrollo

Prepara una base MariaDB de WoL y un usuario con permisos exclusivamente sobre ella,
según el apartado MariaDB de la guía. No uses root para conectar la aplicación.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Completa DB_* y SMTP en .env; conserva aparte tus credenciales existentes.
.venv\Scripts\python migrate_db.py
.venv\Scripts\python app.py
```

En Linux usa `.venv/bin/python`. Abre http://localhost:5000. `database.py` centraliza
PyMySQL con utf8mb4, parámetros `%s`, commit/rollback y cierre de cursores/conexiones.
`CLIENT.FOUND_ROWS` conserva el resultado de actualizaciones de equipos sin cambios.
`database/wol_panel_mariadb.sql` inicializa tablas InnoDB con índices y restricciones;
`migrate_db.py` lo aplica sin importar Flask y conserva datos al reejecutarlo.
Esta es una instalación MariaDB limpia; no copia automáticamente SQL Server.

Variables MariaDB: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
La app ya no utiliza pyodbc, ODBC ni `DB_CONNECTION_STRING`. Nunca apuntes el
instalador o las pruebas a las bases de las otras aplicaciones.

## Producción

Utiliza `.env.production.example`, sin secretos reales en Git. Escucha solo en
`127.0.0.1:5000`; el proxy HTTPS es el único acceso público. La validación exige
DB/SMTP, URL HTTPS y claves privadas de al menos 32 caracteres, cookies Secure,
HttpOnly y SameSite=Lax, y `ALLOW_LOCAL_WOL=0`. El servicio `deploy/wol.service`
arranca `app.py`, incluyendo un único worker, con usuario `wol` sin privilegios.
No se necesita un servicio separado para `alexa_worker.py` en esa instalación.

El virtual host `deploy/nginx-wol.conf` utiliza el certificado Origin CA existente,
con límites propios y el snippet `deploy/wol-cloudflare-realip.conf`. La guía explica
la validación del hostname TLS y cómo añadirlo sin sustituir los otros hosts.
Se retiraron los archivos Docker anteriores para mantener un único despliegue principal.

## Estado SQLite y Alexa

`WOL_STATE_DIR` conserva `session.key` y `auth.sqlite3`; en systemd apunta a
`/var/lib/wol-pro`, fuera del proyecto y con permisos privados. Conserva esta
carpeta y la clave configurada al reiniciar/actualizar. No está en Git.
Los placeholders `?` se conservan exclusivamente en consultas SQLite.

Account Linking usa `/oauth/authorize` y `/oauth/token`, Authorization Code Grant,
código de un solo uso (5 minutos), token de acceso de 1 hora y renovación. Las
Redirect URLs exactas de la skill se validan contra `ALEXA_REDIRECT_URIS`.
Los desafíos de correo se guardan como hash, duran 10 minutos y permiten 5 intentos.

Lambda (`lambda_function.py`) reenvía `/alexa/smarthome` firmado con HMAC-SHA256,
timestamp y `ALEXA_BRIDGE_SECRET`, adicional al token OAuth del propietario.
Discovery y control se limitan a los dispositivos del usuario. AcceptGrant autoriza
Send Alexa Events por usuario y se renuevan sus tokens. Echo usa DeferredResponse,
WakeUp y respuesta final a través del gateway; las órdenes se deduplican y caducan
si no se procesan en 60 segundos. Las pendientes sobreviven al reinicio; las ya
marcadas processing no se repiten automáticamente y caducan para evitar duplicados.

Esta versión usa una sola instancia y una región Alexa por instalación (`NA`, `EU`
o `FE`). Para varias réplicas o regiones simultáneas hace falta adaptar estado/cola
compartidos y selección regional por usuario. La skill pública necesita certificación
Amazon y disponibilidad en los mercados elegidos.

## Verificar

```powershell
python -m unittest -v test_app test_database
```

Se simulan UDP, SMTP y Amazon. `test_mariadb.py` reproduce las pruebas de rutas con
PyMySQL real y añade comprobaciones del esquema, utf8mb4 y migración idempotente.
Solo permite una base local `wol_test_*` y requiere `WOL_TEST_MARIADB=1`.
Consulta `TESTING.md` para crearla con un usuario exclusivo y limpiarla al terminar.

Las pruebas no validan el arranque físico ni la configuración real de Cloudflare,
Nginx o systemd. No se ha desplegado esta versión en Azure.
