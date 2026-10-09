# Publicar WoL Pro en Azure

## Arquitectura y alcance

VM Linux con Docker, proxy HTTPS y Azure SQL/SQL Server. Puede compartir VM con
Cholesterol Game y SpamKill usando un subdominio y contenedor propios. Esta entrega
no modifica ni despliega esos otros proyectos.

Cada persona crea una cuenta, verifica su correo, registra sus equipos y vincula
su propia cuenta con Alexa. Los dispositivos, tokens y permisos se limitan al
propietario. Cada equipo puede guardar su propio destino de router y puerto.

| Método | Orden desde | Entrega en casa |
| --- | --- | --- |
| Alexa / Echo | App Alexa o voz | Echo compatible en la LAN de la PC |
| Router por Internet | Web o Alexa | Router con Wake-on-WAN ya configurado |

El modo local está desactivado en producción. Los equipos existentes se conservan
y muestran un aviso para cambiar de método. Visitar la web de Azure desde el Wi-Fi
de casa no convierte Azure en un emisor local. La app no configura routers.

Esta versión usa una única instancia con volumen persistente para OAuth,
permisos y cola. No habilites réplicas con SQLite en discos independientes.
Para varias instancias hay que compartir/migrar ese estado y la cola.

## Recursos que debes preparar

1. VM Linux x86-64 con Docker Engine, Compose y disco persistente.
2. Base `wol_panel` en Azure SQL o SQL Server con conexión cifrada y accesible
   desde la VM. Para trasladar las cuentas actuales exporta/importa la base
   existente antes de ejecutar la migración; la app no copia datos automáticamente.
3. Subdominio apuntando a la VM, certificado TLS válido y proxy HTTPS.
4. SMTP transaccional con remitente verificado para altas y recuperación.
5. Configuración de la skill según `ALEXA_SETUP.md`.

Publica TCP 443 y, si lo necesitas para TLS/redirección, 80. Compose enlaza 5000
solo a loopback. Se necesita salida HTTPS, SQL y UDP; no un puerto UDP entrante
en Azure. Restringe SQL a la VM/red privada. No expongas la administración del router.

## Instalación en Linux

Sube fuente, plantillas y archivos de despliegue. No uses la `.env` local como
configuración pública. Conserva aparte una copia privada de `instance` si vas a
migrar también sus autorizaciones.

```bash
cp .env.production.example .env.production
chmod 600 .env.production
python3 -c 'import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))'
```

Asigna las dos claves distintas a `FLASK_SECRET_KEY` y `ALEXA_BRIDGE_SECRET`.
Completa dominio, conexión SQL, SMTP y Alexa. Para Azure SQL utiliza ODBC 18,
`Encrypt=yes;TrustServerCertificate=no`. El contenedor incluye ese driver.

```bash
docker compose build
docker compose run --rm wol python migrate_db.py
docker compose up -d
docker compose logs --tail 50 wol
```

La migración crea tablas si faltan y añade los campos de destino conservando
los registros. El worker arranca junto a Waitress. El volumen `wol_state` conserva
el estado entre reinicios. Mantén ese volumen y la clave de sesión al actualizar;
`docker compose down -v` elimina el volumen.

Añade un virtual host a tu proxy usando `deploy/nginx.conf.example`: reemplaza
dominio y rutas TLS, valida con `sudo nginx -t` y recarga Nginx. El ejemplo asume
Nginx instalado en la VM. Si ya tienes un proxy, añade solo el host de WoL sin
sustituir la configuración global de las otras aplicaciones.

`TRUST_PROXY_COUNT=1` confía en un único proxy que reemplaza los encabezados
de IP/protocolo. El backend debe permanecer inaccesible directamente desde Internet.
Producción valida dominio HTTPS, claves, cookies y variables; si faltan datos
se detiene indicando los nombres de las variables, sin mostrar sus valores.

## Verificación antes de abrir las altas

- Prueba dos cuentas: cada una solo debe ver/controlar sus equipos.
- Comprueba correo, recuperación, HTTPS y estado conservado tras reiniciar.
- Prueba el arranque físico con Echo compatible y PC preparada para WoL.
- Prueba desde datos móviles un destino Router ya configurado para Wake-on-WAN.
- Publica la skill tras su certificación en los mercados seleccionados.
- Mantén copias privadas de SQL, configuración y volumen de estado.

Las pruebas locales validan código, aislamiento y paquete UDP; no prueban la VM,
el contenedor construido ni el encendido físico. UDP enviado no confirma arranque.
El modo Router no atraviesa CGNAT ni habilita Wake-on-WAN por sí solo.

## Regiones de Alexa

Empieza con una región de Alexa por instalación; el ejemplo usa `NA` y español
México/Estados Unidos. La disponibilidad de la skill depende de los idiomas y
mercados autorizados por Amazon. `ALEXA_REGION` aplica a toda esta instalación.
Para atender NA/EU/FE simultáneamente habría que añadir región por usuario y
endpoints Lambda regionales. No se promete disponibilidad mundial con un único NA.

## Referencias

- [WoL y Echo compatibles](https://developer.amazon.com/docs/alexaplus/device-apis/alexa-wakeonlancontroller.html).
- [Microsoft ODBC en Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server?view=sql-server-ver17).
