# Acceso nativo de la app

La app móvil dibuja sus propios formularios para iniciar sesión, registrar la cuenta, verificar el correo y recuperar/cambiar la contraseña. Reutiliza usuarios, correo, códigos y sesiones existentes.

`native_auth.py` añade `GET /mobile/bridge` (documento vacío) y `GET /api/mobile/v1/auth/session`. Las operaciones JSON son `POST /api/mobile/v1/auth/{login,register,verify,resend,forgot,reset}`. Las escrituras necesitan el token CSRF del bootstrap; registro y recuperación usan códigos de seis dígitos que caducan a los diez minutos y tienen cinco intentos. Los límites de solicitudes de acceso, registro y recuperación comparten sus contadores con las rutas web.

La conexión interna de la app mantiene la cookie HttpOnly en una WebView invisible del mismo origen. No carga formularios web, anuncios ni enlaces externos. Al iniciar sesión se rota el CSRF. Conservar sesión es opcional y usa la caducidad de 30 días y revocación existentes.

## Actualización

Actualizar primero este backend, incluyendo `app.py` y el nuevo `native_auth.py`, y reiniciar `wol.service`. Después compilar e instalar la app actualizada. No hay nueva migración ni variable de entorno para este acceso. Las rutas web, el agente y Alexa conservan sus flujos. Los clientes anteriores pueden seguir utilizando el acceso web.

```sh
python -m unittest test_native_auth test_app test_windows_agent test_database test_monetization
```

Las pruebas usan cuentas y bases de datos temporales y correo simulado. No envían órdenes a equipos reales. La comprobación de dispositivo físico y la actualización de Azure siguen pendientes.
