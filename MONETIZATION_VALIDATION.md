# Validación de monetización — 10 de octubre de 2026

## Comprobaciones locales

- Backend: 153 pruebas pasaron en la ejecución completa de `test_app`, `test_windows_agent` y `test_monetization`. Después se añadió una regresión de reemplazo de suscripciones; las 17 pruebas de monetización pasaron con ese ajuste (154 casos distintos en la suite final).
- Se comprueban cuotas Free/Premium, selección al vencer, Alexa Discovery, restricciones en cola y antes de ejecutar, cancelación, propiedad de recibos, pagos pendientes/cancelados/expirados, reemplazo de tokens, firma ECDSA sobre la consulta original, recompensa de treinta minutos, frecuencia publicitaria, TOTP, CSRF, suspensión, auditoría, promociones y solicitudes de eliminación.
- App: 24 pruebas pasaron; TypeScript y ESLint sin errores. Exportación de bundles Hermes Android e iOS completada.
- Android nativo: `:app:assembleDebug` completó correctamente con Expo 57, AdMob 17 y Expo IAP 6. El manifiesto corresponde a 1.1.0 / código 3, incluye Billing y bloquea `com.google.android.gms.permission.AD_ID` en modo inicial. El SDK también aporta permisos AdServices; revisar el manifiesto del AAB final y las declaraciones al activar anuncios.
- Windows: 38 pruebas pasaron y la publicación autónoma win-x64 se compiló. Se generaron `artifacts/WoLPro-Agent-win-x64.zip`, `artifacts/WoLPro-Agent-Setup.exe` y sus SHA256. El instalador es 0.4.0 y no está firmado digitalmente. No se instaló sobre el agente del usuario durante esta tarea.
- Admin: `node --check app.js` pasó. Revisión en navegador con cuenta y datos ficticios aislados: acceso TOTP, resumen, detalle de usuario, política de anuncios, confirmación con motivo y auditoría. No se modificó una cuenta real ni Azure.

## Integración continua

Los repositorios incluyen CI para backend, MariaDB 11.4 aislada, app, agente Windows y frontend administrativo. La prueba MariaDB adicional compite con dos registros simultáneos Free para comprobar el bloqueo InnoDB y la cuota; no se ejecutó contra una base de producción. Consultar los resultados de Actions de la rama antes de desplegar.

## Pendiente de las cuentas reales

Azure y Admin se despliegan manualmente. Google Play requiere crear productos/oferta, credenciales restringidas, RTDN, reconciliación y compras de prueba. AdMob requiere unidades, UMP y SSV reales; AdSense requiere unidades y CMP. El estado predeterminado no inicia cobros ni solicita anuncios.

El APK de comprobación es debug; no sustituye el AAB firmado con la clave de carga existente. La exportación iOS valida JavaScript, no una compilación Xcode. La validación de compras Apple debe implementarse antes de vender en iOS. La firma digital del instalador Windows y la prueba con el PC físico siguen siendo pasos separados.

Consulta [MONETIZATION_DEPLOYMENT.md](MONETIZATION_DEPLOYMENT.md) para respaldos, instalación manual, configuración y recuperación.
