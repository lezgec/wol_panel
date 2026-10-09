# WoL Pro

Aplicación web para registrar equipos y encenderlos mediante Wake-on-LAN, con soporte para Alexa.

## Funciones

- Cuentas de usuario y gestión de equipos por nombre y dirección MAC.
- Encendido con Alexa mediante un Echo compatible en la red del equipo.
- Encendido desde el navegador mediante un router preparado para Wake-on-WAN.
- Encendido local cuando el servidor está en la misma red que el equipo.

El equipo debe tener Wake-on-LAN habilitado. La aplicación no configura el router y enviar una orden no confirma que el equipo haya arrancado.

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
- `POST /api/mobile/v1/devices/{id}/wake`: comprueba propiedad y devuelve instrucciones Alexa o «Próximamente» para encendido directo.

Todas las escrituras requieren sesión y cabecera `X-CSRF-Token`; creación y edición tienen límites de solicitudes. Las respuestas no se almacenan en caché. El encendido directo está deshabilitado en el cliente móvil; Alexa devuelve instrucciones. No se requieren cambios de tablas ni credenciales nuevas.

## Pruebas

```bash
python -m unittest -v test_app test_database test_windows_agent
```

Más detalles en [TESTING.md](TESTING.md).

## Control Windows

El [agente Windows](https://github.com/lezgec/wolpro_agent) permite vincular un PC mediante tu cuenta, abrir aplicaciones autorizadas y apagarlo con una cuenta atrás cancelable. El panel incorpora acciones e historial; Alexa puede usar las mismas órdenes.

Para activarlo en Azure, ejecuta `python migrate_db.py`, añade `ENABLE_WINDOWS_AGENT=1` al `.env` existente y reinicia tu servicio. Consulta los pasos en [WINDOWS_AGENT.md](WINDOWS_AGENT.md) y la [skill de acciones Alexa](alexa-custom/README.md).
