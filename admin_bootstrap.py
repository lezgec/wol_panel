"""Run locally on Azure as the service owner; never a public HTTP endpoint."""
import argparse
import base64
import getpass
import hashlib
import secrets
import time
from urllib.parse import quote


def main():
    parser=argparse.ArgumentParser(description='Crear propietario WoL Pro Admin con TOTP')
    parser.add_argument('--email',required=True)
    args=parser.parse_args()
    from app import plans
    row=plans.db.fetch_one('SELECT id,email,password,is_verified FROM users WHERE email=%s',(args.email.strip().lower(),))
    from werkzeug.security import check_password_hash
    if not row or not row[3] or not check_password_hash(row[2],getpass.getpass('Contraseña de la cuenta: ')):
        raise SystemExit('Cuenta verificada y contraseña válidas requeridas.')
    with plans.state() as db:
        if db.execute('SELECT user_id FROM admin_owners WHERE user_id=?',(str(row[0]),)).fetchone():
            raise SystemExit('El propietario ya existe. No se cambió su configuración.')
    secret=base64.b32encode(secrets.token_bytes(20)).decode()
    print('Guarda esta clave SOLO en tu autenticador. No la publiques ni la envíes al soporte:')
    print(secret)
    print('otpauth://totp/'+quote('WoL Pro Admin:'+row[1],safe='')+'?secret='+secret+'&issuer=WoL%20Pro%20Admin')
    code=getpass.getpass('Código de seis dígitos de tu autenticador: ')
    from admin_api import totp
    counter=int(time.time())//30
    if not secrets.compare_digest(totp(secret,counter),code): raise SystemExit('Código inválido. No se creó el propietario.')
    with plans.state() as db:
        db.execute('INSERT INTO admin_owners(user_id,secret,last_counter) VALUES (?,?,?)',(str(row[0]),secret,counter))
        db.execute('INSERT INTO admin_audit(actor,action,target,created,before_json,after_json,reason) VALUES (?,?,?,?,?,?,?)',
                   (str(row[0]),'owner_bootstrap',str(row[0]),int(time.time()),'{}','{"role":"owner"}','Alta local verificada con contraseña y TOTP'))
    print('Propietario creado. Espera al siguiente código para iniciar sesión.')


if __name__=='__main__': main()
