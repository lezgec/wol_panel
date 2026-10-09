# Instalar WoL Pro en vm-apps-ubuntu

Arquitectura: Ubuntu 24.04 + Flask/Waitress + MariaDB local + SQLite persistente
+ systemd + Nginx + Cloudflare Full (strict). No requiere Docker, SQL Server ni
Azure SQL. Estos pasos solo añaden WoL; no sustituyen hosts ni bases de SpamKill
o Cholesterol Game. La instalación es limpia; no importa datos del antiguo SQL Server.

## 1. Acceso y código

Necesitas una sesión SSH administrativa y acceso de lectura al repositorio privado
por SSH. Usa una clave autorizada en GitHub; no incluyas tokens en la URL del repo.
Desde tu ordenador, reemplaza los datos de conexión:

```bash
ssh USUARIO_SSH@IP_PUBLICA_VM
```

En la VM:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends python3-venv python3-pip git
id wol >/dev/null 2>&1 || sudo useradd --system --user-group --home-dir /var/lib/wol-pro --shell /usr/sbin/nologin wol
sudo install -d -m 0750 -o "$USER" -g wol /srv/apps/wakeonlan
git clone git@github.com:lezgec/wol_panel.git /srv/apps/wakeonlan
cd /srv/apps/wakeonlan
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo install -d -m 0700 -o wol -g wol /var/lib/wol-pro
```

`git clone` presupone que el directorio reservado está vacío. Si ya contiene este
repositorio, utiliza `git pull --ff-only` conservando `.env` y el estado persistente.
MariaDB y Nginx ya están instalados: no se instalan ni se cambian sus servicios globales.

## 2. Base y usuario exclusivo

Abre el cliente administrativo evitando guardar contraseñas en su historial:

```bash
sudo env MYSQL_HISTFILE=/dev/null mariadb
```

Ejecuta este SQL. **Sustituye la contraseña de ejemplo por una privada antes de ejecutarlo.**
El usuario de la app tiene permisos solo en `wol_panel`, desde loopback; no usa root.

```sql
CREATE DATABASE IF NOT EXISTS wol_panel
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'wol_user'@'127.0.0.1'
  IDENTIFIED BY 'REEMPLAZAR_POR_CONTRASENA_PRIVADA';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON wol_panel.* TO 'wol_user'@'127.0.0.1';
SHOW GRANTS FOR 'wol_user'@'127.0.0.1';
EXIT;
```

`CREATE USER IF NOT EXISTS` no cambia la contraseña de un usuario existente.
Si ya existe, conserva su contraseña y úsala en `.env`. No se ejecuta `FLUSH
PRIVILEGES`, porque las sentencias de cuentas aplican inmediatamente.
Los permisos DDL permiten ejecutar el instalador idempotente; no otorgan acceso
ni permisos de creación/eliminación sobre otras bases.

## 3. Configuración privada

```bash
test -e .env || sudo install -m 0640 -o root -g wol .env.production.example .env
sudoedit /srv/apps/wakeonlan/.env
```

En una actualización, conserva la `.env` existente. Completa `DB_PASSWORD` con
la contraseña anterior, SMTP y las credenciales Alexa.
Genera dos claves distintas en la VM y colócalas en `FLASK_SECRET_KEY` y
`ALEXA_BRIDGE_SECRET`; no las subas al repositorio:

```bash
.venv/bin/python -c 'import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))'
```

Mantén estas opciones:

```dotenv
APP_ENV=production
PUBLIC_BASE_URL=https://wol.luiszamora.dev
HOST=127.0.0.1
PORT=5000
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=wol_panel
DB_USER=wol_user
COOKIE_SECURE=1
ALLOW_LOCAL_WOL=0
TRUST_PROXY_COUNT=1
WOL_STATE_DIR=/var/lib/wol-pro
```

`SMTP_FROM` debe ser un remitente autorizado, por ejemplo `Soporte WoL Pro
<support@luiszamora.dev>`. El servidor comprueba las variables de producción y
rechaza claves cortas, root, URL sin HTTPS, cookies inseguras y el bind público.
Alexa puede configurarse después: mientras sus credenciales estén vacías, la
vinculación informa que no está disponible y no acepta órdenes sin autorización.

## 4. Inicializar y arrancar

```bash
sudo -u wol .venv/bin/python migrate_db.py
sudo install -m 0644 deploy/wol.service /etc/systemd/system/wol.service
sudo systemd-analyze verify /etc/systemd/system/wol.service
sudo systemctl daemon-reload
sudo systemctl enable --now wol.service
sudo systemctl status wol.service --no-pager
sudo journalctl -u wol.service -n 50 --no-pager
```

El SQL de instalación está en `database/wol_panel_mariadb.sql`. El instalador no
importa Flask ni crea SQLite. Crea tablas con `IF NOT EXISTS`, InnoDB y utf8mb4;
repetirlo conserva registros. No modifica estructuras desconocidas de otra app.

`python app.py` inicia Waitress (cuatro hilos) y un único worker Alexa. No añadas
otro servicio para `alexa_worker.py` con esta instalación. systemd reinicia el
proceso ante fallos y lo inicia al arrancar Ubuntu. Corre como `wol`, con código
protegido de escritura y archivos de estado privados en `/var/lib/wol-pro`.

## 5. Virtual host Nginx y certificado existente

Comprueba que el certificado existente cubra `wol.luiszamora.dev` o `*.luiszamora.dev`:

```bash
sudo openssl x509 -in /etc/nginx/ssl/spamkill-origin.pem -noout -checkhost wol.luiszamora.dev
sudo install -m 0644 deploy/wol-cloudflare-realip.conf /etc/nginx/snippets/wol-cloudflare-realip.conf
sudo install -m 0644 deploy/nginx-wol.conf /etc/nginx/sites-available/wol.luiszamora.dev
sudo ln -s /etc/nginx/sites-available/wol.luiszamora.dev /etc/nginx/sites-enabled/wol.luiszamora.dev
sudo nginx -t
sudo systemctl reload nginx
```

Si el enlace ya existe, no hace falta crearlo otra vez. Si el certificado no cubre
WoL, prepara uno que lo cubra en archivos propios y ajusta solamente el host WoL;
no reemplaces los certificados de las aplicaciones existentes. Origin CA requiere
acceso a través del proxy Cloudflare para la confianza TLS en navegadores.

El host usa `/etc/nginx/ssl/spamkill-origin.pem` y `.key`, redirige HTTP a HTTPS y
proxy a `127.0.0.1:5000`. Las zonas `wol_*` son propias. Nginx reemplaza los headers
hacia Flask, y solo acepta `CF-Connecting-IP` de las redes oficiales del snippet.
Flask confía en ese único proxy. La lista de redes debe revisarse al actualizar.
Los límites Nginx toleran ráfagas de OAuth/Lambda; la app limita además por IP/usuario.
No se sirven archivos del proyecto y el acceso se registra sin query strings,
tokens de cabecera ni cuerpos de petición. No habilites logs de depuración de secretos.

## 6. DNS y Cloudflare

En la zona `luiszamora.dev` crea o actualiza únicamente el registro **A** `wol`:

- Contenido: IP pública de `vm-apps-ubuntu`.
- Proxy: **Proxied** (nube naranja).
- TTL: Auto.
- SSL/TLS: **Full (strict)**, compatible con Origin CA válido para el hostname.
- Caché: regla para `wol.luiszamora.dev` con **Bypass cache**, incluyendo OAuth.

Conserva los registros y rutas de las otras aplicaciones. Comprueba que las reglas
Cloudflare no presenten un desafío de navegador a `/oauth/token` o `/alexa/smarthome`,
porque Amazon y Lambda necesitan respuestas de API. No desactives la seguridad de
los otros hosts. En Azure no añadas reglas entrantes para 5000, 3306 ni UDP.
WoL Router usa exclusivamente UDP saliente a un destino público ya preparado.

## 7. Verificar la instalación

```bash
cd /srv/apps/wakeonlan
sudo systemctl is-active wol.service mariadb nginx
sudo ss -ltnp '( sport = :5000 or sport = :3306 )'
curl -I http://127.0.0.1:5000/login -H 'Host: wol.luiszamora.dev'
curl -I https://wol.luiszamora.dev/login
sudo -u wol .venv/bin/python -c "from database import fetch_one; print('MariaDB OK:', fetch_one('SELECT 1')[0] == 1)"
sudo nginx -t
sudo journalctl -u wol.service -n 100 --no-pager
```

5000 debe escuchar solo en `127.0.0.1`. Verifica que MariaDB tampoco escuche en
una interfaz pública; si su bind ya es local, consérvalo. Cualquier cambio global
de MariaDB debe coordinarse con las otras aplicaciones; estos archivos no lo realizan.
Comprueba registro/correo, recuperación y dos cuentas distintas. Para probar
persistencia, inicia sesión, vincula Alexa, reinicia `wol.service` y comprueba que
las autorizaciones y equipos continúen disponibles.

## 8. Actualizaciones, copias y capacidad

```bash
cd /srv/apps/wakeonlan
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
sudo -u wol .venv/bin/python migrate_db.py
sudo systemctl restart wol.service
sudo journalctl -u wol.service -n 50 --no-pager
free -h
ps -o pid,rss,%cpu,cmd -C python -C python3
```

Conserva `.env`, sus permisos, la clave de sesión y `/var/lib/wol-pro`. Mantén
copias privadas de la base `wol_panel` y de la carpeta de estado; usa la API de
backup de SQLite o detén WoL al copiarla, sin detener las demás aplicaciones.
Esta instalación utiliza una sola instancia y SQLite local; no habilites réplicas
con discos separados. La VM tiene poca RAM: comprueba el consumo combinado con
SpamKill, PHP y MariaDB antes de admitir carga pública. No se ha medido esa VM.

## Alexa y pruebas

Consulta `ALEXA_SETUP.md` para Lambda, OAuth y certificación. Las pruebas
reproducibles están en `TESTING.md`. Se probaron 87 casos en Windows/Python 3.13,
incluidos 42 con MariaDB 10.11.14 real y una base temporal aislada. No se enviaron
correos ni paquetes WoL reales. systemd/Nginx/Cloudflare y el encendido físico
requieren validación en Ubuntu y hardware; no se ha desplegado en Azure.

## Referencias oficiales

- [MariaDB CREATE TABLE e idempotencia](https://mariadb.com/docs/server/server-usage/tables/create-table).
- [PyMySQL y sus transacciones](https://pymysql.readthedocs.io/en/latest/modules/connections.html).
- [Cloudflare Origin CA](https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/).
- [Nginx límites](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html).
- [Nginx IP del cliente](https://nginx.org/en/docs/http/ngx_http_realip_module.html).
