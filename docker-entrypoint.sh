#!/bin/sh
# Solo para desarrollo local (docker-compose.yml). En producción, Render
# ejecuta el Dockerfile con gunicorn y las migraciones se lanzan aparte.
set -e

flask db upgrade
flask db-seed

exec "$@"
