#!/bin/sh
# Arranque en producción (Render). Es el CMD del Dockerfile.
#
# Las migraciones y la siembra van aquí y no en un paso aparte porque el
# plan gratuito de Render no ofrece comando de pre-despliegue: si no se
# lanzan al arrancar el contenedor, la base de Neon se queda sin tablas y
# sin el usuario único, y la aplicación responde 500 en todas las rutas.
# Ambos comandos son idempotentes, así que repetirlos en cada arranque (o
# en cada despertar tras dormirse el servicio) no tiene efecto.
set -e

echo "==> Aplicando migraciones"
flask db upgrade

echo "==> Sembrando usuario y banco si hace falta"
flask db-seed

echo "==> Arrancando gunicorn"
exec gunicorn \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
