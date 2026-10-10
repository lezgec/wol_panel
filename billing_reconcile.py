"""Use a systemd timer. No purchase tokens or provider exception bodies in output."""
if __name__=='__main__':
    from app import billing
    import json
    if not billing.enabled: raise SystemExit('Compras desactivadas; no hay configuración de Google Play.')
    result=billing.refresh()
    print(json.dumps(result))
    if result['failed']: raise SystemExit(1)
