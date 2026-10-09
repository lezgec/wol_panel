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

## Pruebas

```bash
python -m unittest -v test_app test_database
```

Más detalles en [TESTING.md](TESTING.md).
