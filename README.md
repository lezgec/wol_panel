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
- `POST /api/mobile/v1/devices/{id}/wake`: requiere sesión y cabecera `X-CSRF-Token`; comprueba propiedad y reutiliza la lógica del panel.

Las respuestas no se almacenan en caché. Las órdenes móviles comparten el límite de solicitudes del panel. Alexa devuelve instrucciones; enviar WoL no confirma que el equipo esté encendido. No se requieren cambios de tablas ni credenciales nuevas.

## Pruebas

```bash
python -m unittest -v test_app test_database
```

Más detalles en [TESTING.md](TESTING.md).
