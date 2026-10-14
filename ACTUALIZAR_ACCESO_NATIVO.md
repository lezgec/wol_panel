# Actualizar WoL Pro desde Git

La entrega completa está en `main` de `wol_panel`, `wol-pro-app` y `wolpro_agent`. El administrador `wolpro_admin` utiliza `codex/monetization` como rama principal. La rama `codex/monetization` de los cuatro también conserva la entrega. Publicar código no actualiza automáticamente Azure, la app instalada ni el instalador descargable.

## Backend en Azure

Desde PowerShell de Windows:

```powershell
ssh -i 'C:\Users\lezgo\Downloads\key-mis-apps.pem' azureuser@130.131.32.129
```

En Ubuntu, comprueba primero `git status --short` dentro de `/srv/apps/wakeonlan`. Si hay cambios locales, consérvalos y revísalos antes de continuar. Cuando esté limpio:

```bash
set -e
cd /srv/apps/wakeonlan
test -z "$(git status --porcelain)"
sudo mkdir -p /var/backups/wol-pro
wol_backup=$(sudo mktemp -d /var/backups/wol-pro/git-update-XXXXXX)
sudo chmod 700 "$wol_backup"
git rev-parse HEAD | sudo tee "$wol_backup/commit.txt"
sudo tar -czf "$wol_backup/codigo.tar.gz" --exclude=.git --exclude=.venv --exclude=venv --exclude=__pycache__ --exclude=instance .
echo "RESPALDO=$wol_backup"
git fetch origin
git switch main
git pull --ff-only origin main
sudo systemctl restart wol.service
sudo systemctl is-active wol.service
curl -fsS https://wol.luiszamora.dev/api/mobile/v1/auth/session | python3 -c 'import json,sys; print("Acceso:", json.load(sys.stdin)["phase"])'
curl -fsS -o /dev/null -w 'Puente HTTP: %{http_code}\n' https://wol.luiszamora.dev/mobile/bridge
```

Esperado: `active`, `Acceso: login`, `Puente HTTP: 200`. El acceso nativo y los tours no requieren nuevas migraciones ni variables de entorno. Para instalaciones anteriores a la entrega de planes/control, consulta primero `MONETIZATION_DEPLOYMENT.md`. Conserva `.env`, MariaDB y `WOL_STATE_DIR`; el respaldo contiene configuración privada.

Si falla: `sudo journalctl -u wol.service -n 60 --no-pager`. Para volver al commit anterior en la misma sesión: `wol_previous=$(sudo cat "$wol_backup/commit.txt")`, `git switch --detach "$wol_previous"` y `sudo systemctl restart wol.service`.

## App móvil y agente Windows

En PowerShell, dentro de los repositorios locales de backend, app y agente, ejecuta `git fetch origin`, `git switch main` y `git pull --ff-only origin main`. Para `wolpro_admin`, utiliza `codex/monetization` en lugar de `main`. Después:

- App: desde `C:\Users\lezgo\Desktop\wol-pro-app`, ejecuta `npm ci`, `npm run typecheck`, `npm run lint` y `npm test`. Compila Android con `:app:assembleRelease` desde Android Studio o `android\gradlew.bat`. Instala el nuevo `android\app\build\outputs\apk\release\app-release.apk`. La firma debe coincidir con la instalación actual. Para Google Play usa tu clave de publicación, AAB y nuevo código de versión. Consulta `wol-pro-app/README.md`.
- Agente: abre `C:\Users\lezgo\Desktop\wolpro_agent\wolpro_agent.sln` en Visual Studio 2022. Consulta su README para generar el instalador. El código actualizado no reemplaza automáticamente el `.exe` disponible en Azure; hay que subirlo después de generar una nueva compilación. `dotnet test wolpro_agent.sln -c Release` y `scripts/Verify-UI.ps1` verifican el código sin ejecutar órdenes reales.

## Administrador

Si `/opt/wolpro_admin` es un checkout Git limpio, ejecuta allí `git fetch origin`, `git switch codex/monetization` y `git pull --ff-only origin codex/monetization`. Si es una carpeta estática, descarga el repositorio privado en una carpeta distinta y copia el `app.js` actualizado a `/opt/wolpro_admin/app.js`, respaldando antes el existente. Abre de nuevo la página para cargar el JavaScript nuevo. Los cambios de esta entrega son de interfaz y documentación.
