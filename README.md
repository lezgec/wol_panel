# WoL Pro

Panel y backend de WoL Pro: cuentas, encendido con Alexa y control remoto mediante el agente Windows, desde la web o la app.

## Funciones

- Cuentas de usuario y gestión de equipos por nombre y dirección MAC.
- Encendido con Alexa mediante un Echo compatible en la red del equipo.
- Apagado integrado con cuenta atrás cancelable, y aplicaciones/comandos autorizados mediante el agente.
- Mi plan: Free con un equipo activo; Premium con diez y aplicaciones/comandos, sin publicidad.
- Suscripciones verificadas, publicidad con límites y administrador en un repositorio independiente.

El equipo debe tener Wake-on-LAN habilitado y un Echo compatible para encender con Alexa. El encendido por router/Wake-on-WAN se retiró. Las órdenes al agente siguen usando HTTPS por Internet, sin abrir puertos entrantes en casa; requieren el PC encendido, sesión Windows y permisos locales.

Consulta [MONETIZATION_DEPLOYMENT.md](MONETIZATION_DEPLOYMENT.md) para la actualización manual, respaldo y configuración de compras/anuncios. Los proveedores están desactivados inicialmente. El [administrador](https://github.com/lezgec/wolpro_admin) usa acceso independiente con contraseña, TOTP y auditoría.

## Ejecutar

Requiere Python y una base de datos MariaDB con un usuario propio.

1. Instala las dependencias: `python -m pip install -r requirements.txt`.
2. Copia `.env.example` a `.env` y completa los datos de MariaDB, correo y Alexa.
3. Inicializa las tablas: `python migrate_db.py`.
4. Inicia la aplicación: `python app.py`.

Abre [http://localhost:5000](http://localhost:5000).

Las cuentas y los equipos se guardan en MariaDB. Conserva la carpeta indicada en `WOL_STATE_DIR` y la clave `FLASK_SECRET_KEY` para mantener la vinculación con Alexa al actualizar. No subas `.env` ni credenciales al repositorio.

## Cliente móvil

La app [wol-pro-app](https://github.com/lezgec/wol-pro-app) reutiliza el acceso web y muestra equipos en una pantalla nativa. La API versionada usa la sesión Flask existente:

- `GET /api/mobile/v1/devices`: equipos del usuario, correo y token CSRF.
- `POST /api/mobile/v1/devices`: crea un dispositivo con Alexa, nombre y MAC.
- `PUT /api/mobile/v1/devices/{id}`: edita nombre y MAC, conservando el método y la configuración existentes.
- `POST /api/mobile/v1/logout`: cierra la sesión.
- `POST /api/mobile/v1/devices/{id}/wake`: comprueba propiedad y equipo activo; devuelve instrucciones Alexa o rechaza el método retirado.

Todas las escrituras requieren sesión y cabecera `X-CSRF-Token`; creación y edición tienen límites de solicitudes y cuota de plan. Las respuestas no se almacenan en caché. El control de PC y Mi plan usan la misma sesión; el servidor aplica los permisos a todos los canales. Se añaden tablas privadas idempotentes para planes y administración al estado existente.

## Pruebas

```bash
python -m unittest -v test_app test_database test_windows_agent
```

Más detalles en [TESTING.md](TESTING.md).

## Control de PC

El [agente Windows](https://github.com/lezgec/wolpro_agent) permite vincular un PC mediante tu cuenta, abrir aplicaciones, ejecutar comandos CMD/PowerShell guardados y autorizados en ese PC, y apagarlo con una cuenta atrás cancelable. En el mismo panel, pulsa **Añadir equipo** y expande una tarjeta para encender, modificar, vincular, gestionar acciones y consultar su historial. Alexa puede usar las mismas órdenes. Los comandos personalizados no usan la cuenta atrás del apagado integrado.

Para activarlo en Azure, ejecuta `python migrate_db.py`, añade `ENABLE_WINDOWS_AGENT=1` al `.env` existente y reinicia tu servicio. Consulta los pasos en [WINDOWS_AGENT.md](WINDOWS_AGENT.md) y la [ampliación de la misma skill Alexa](alexa-custom/README.md).

El botón **Descargar agente para Windows** sirve el instalador desde Azure. Copia `WoLPro-Agent-Setup.exe` de la Release del agente a `WOL_STATE_DIR/downloads/`; el panel muestra el botón cuando está disponible. Mientras no hayas subido el instalador, sigue funcionando el ZIP portátil existente en esa carpeta. Los usuarios no necesitan acceso a GitHub.

Desde el agente 0.3.3 puedes activar un servicio que confirma la conexión del PC antes de iniciar sesión en Windows. El panel actualiza el estado cada cinco segundos y distingue conexión del PC y disponibilidad de las acciones de la sesión. Actualiza el backend, ejecuta `python migrate_db.py` y activa el servicio desde el agente con permisos de administrador. Las aplicaciones y comandos siguen ejecutándose dentro de la sesión del usuario.
