#!/usr/bin/env bash
set -euo pipefail
umask 077

stage="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
base=/srv/apps/wakeonlan
admin=/opt/wolpro_admin
files=(monetization.py admin_api.py templates/_ads_slot.html templates/dashboard.html templates/privacy.html static/web_ads.js static/dashboard.css)
cd "$stage"
sha256sum --check SHA256SUMS
test -f "$base/.env"
test -f "$admin/app.js"
test -d /var/backups/wol-pro
for name in "${files[@]}"; do test -f "$base/$name"; done
"$base/.venv/bin/python" - "$stage" <<'PY'
import sys
from pathlib import Path
from jinja2 import Environment
stage = Path(sys.argv[1])
for name in ('monetization.py', 'admin_api.py'):
    compile((stage / name).read_bytes(), name, 'exec')
for path in (stage / 'templates').glob('*.html'):
    Environment().parse(path.read_text())
print('SINTAXIS_OK')
PY

backup="$(mktemp -d /var/backups/wol-pro/web-ads-XXXXXX)"
for name in "${files[@]}"; do
    mkdir -p "$backup/backend/$(dirname -- "$name")"
    cp -p "$base/$name" "$backup/backend/$name"
done
cp -p "$base/.env" "$backup/.env"
cp -p "$admin/app.js" "$backup/admin-app.js"
echo "RESPALDO=$backup"
restore() {
    trap - ERR
    for name in "${files[@]}"; do cp -p "$backup/backend/$name" "$base/$name"; done
    cp -p "$backup/.env" "$base/.env"
    cp -p "$backup/admin-app.js" "$admin/app.js"
    systemctl restart wol.service || true
    echo "Se restauró el código y entorno anterior. RESPALDO=$backup" >&2
    exit 1
}
trap restore ERR
for name in "${files[@]}"; do
    install -o "$(stat -c %u "$base/$name")" -g "$(stat -c %g "$base/$name")" -m "$(stat -c %a "$base/$name")" "$stage/$name" "$base/$name"
done
install -o "$(stat -c %u "$admin/app.js")" -g "$(stat -c %g "$admin/app.js")" -m "$(stat -c %a "$admin/app.js")" "$stage/admin-app.js" "$admin/app.js"
"$base/.venv/bin/python" - "$base/.env" <<'PY'
import os, shutil, sys, tempfile
from pathlib import Path
from dotenv import set_key
env = Path(sys.argv[1])
original = env.stat()
fd, temporary = tempfile.mkstemp(prefix='.web-ads-', dir=env.parent)
os.close(fd)
try:
    shutil.copy2(env, temporary)
    for key, value in {
        'ADSENSE_CLIENT': 'ca-pub-8703217786138724',
        'ADSENSE_BANNER_SLOT': '7179749843',
        'ADSENSE_RECTANGLE_SLOT': '9557581305',
        'ADS_WEB_READY': '0',
        'ADS_WEB_TEST_USER_IDS': '1',
    }.items():
        set_key(temporary, key, value)
    os.chown(temporary, original.st_uid, original.st_gid)
    os.chmod(temporary, original.st_mode & 0o777)
    os.replace(temporary, env)
finally:
    Path(temporary).unlink(missing_ok=True)
PY
systemctl restart wol.service
systemctl is-active --quiet wol.service
trap - ERR
echo WEB_ADS_PREPARADA_SIN_ACTIVAR
echo 'AdSense y las decisiones de privacidad se comprobarán tras aprobarse el sitio.'
echo 'La política y las variables de AdMob/Android se conservan.'
