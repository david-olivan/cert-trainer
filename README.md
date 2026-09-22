# Entrenador AIB-C01

Herramienta personal de preparación para la certificación AWS Certified AI Business Strategist (AIB-C01). Un solo usuario.

## Estado

Fase 1 completa: acceso, banco de preguntas, los cuatro modos de práctica, importación con vista previa y exportación. La interfaz sigue el lenguaje visual de macOS, con modo claro y oscuro automáticos. Listo para desplegar: ver más abajo.

## Estructura

```
CLAUDE.md                          contexto permanente y decisiones tomadas
SPEC.md                            qué construir, por fases
render.yaml                        el servicio de Render (la base va aparte, en Neon)
docker-start.sh                    arranque en producción: migra, siembra y cede a gunicorn
.github/workflows/                 batería de humo, despliegue y copia del banco
tests/                             lo que tiene que pasar antes de desplegar
app/                               la aplicación Flask
app/static/css/app.css             tokens de diseño y componentes (única hoja de estilos)
app/templates/                     plantillas Jinja, incluidos los <template> de la tanda
data/questions.seed.json           44 preguntas originales (contenido curado)
reference/entrenador-artefacto.html  prototipo de un archivo: referencia de UI y lógica
reference/formato-preguntas.md     esquema del JSON de importación
```

## Arranque local

```bash
cp .env.example .env        # y rellena SECRET_KEY y ADMIN_PASSWORD_HASH
docker compose up --build
```

Para generar el hash de la contraseña:

```bash
python -c "from werkzeug.security import generate_password_hash as g; print(g(input('contraseña: ')))"
```

**Importante al pegarlo en `.env`:** el hash de scrypt lleva `$` como separador (`scrypt:N:r:p$sal$hash`). Docker Compose interpola `$NOMBRE` dentro de los valores de `env_file`, así que cada `$` del hash debe escaparse como `$$` en `.env` — si no, Compose lo trunca silenciosamente y el login falla (con un hash mal formado del todo, incluso puede dar un error 500 en vez de "credenciales incorrectas"). Duplica cada `$` a mano antes de guardar el archivo.

Si el login sigue fallando después de reconstruir, comprueba que no haya otro proceso escuchando en el puerto 8000 (`netstat -ano | findstr ":8000"` en Windows): un `flask run` suelto fuera de Docker, apuntando al mismo `data/app.db`, puede interceptar las peticiones y confundir el diagnóstico.

## Datos de demostración

Con la base recién sembrada todas las pantallas salen vacías: el medidor a «—», sin historial y sin fallos que repasar. Para revisar la interfaz con datos realistas:

```bash
flask db-seed-demo          # genera 6 sesiones y ~73 intentos sintéticos
flask db-seed-demo --reset  # los regenera, borrando el progreso anterior
flask db-reset-progress     # borra todo el progreso y deja la base limpia
```

La semilla es fija, así que dos ejecuciones producen exactamente los mismos datos y las capturas de pantalla son comparables. El perfil está pensado a propósito para que cada dominio caiga en un estado distinto del medidor. Estos comandos solo escriben en `study_sessions` y `attempts`: **el banco de preguntas no se toca nunca**.

El mismo borrado está disponible desde la interfaz, en el botón «Reiniciar» de la barra superior.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Es una batería de humo, no una suite completa: comprueba lo que rompe un despliegue (la cadena de conexión, las migraciones, la siembra, el acceso y que las rutas siguen protegidas). Por defecto corre contra un sqlite desechable; para correrla contra Postgres, exporta `TEST_DATABASE_URL`. En CI siempre corre contra Postgres.

## Despliegue

Render, plan gratuito, con base de datos Postgres externa (Neon). Los servicios gratuitos de Render tienen sistema de archivos efímero y sus bases Postgres caducan a los 30 días: por eso la base va fuera.

El servicio se duerme a los 15 minutos sin tráfico y tarda alrededor de un minuto en despertar. Es el precio del plan gratuito y está asumido.

### Puesta en marcha, una sola vez

1. **Neon**: crea un proyecto en `eu-central-1` (la misma región que Fráncfort, donde va el servicio) y copia la cadena de conexión. Se pega tal cual: `app/config.py` la reescribe a `postgresql+psycopg://` al arrancar, porque SQLAlchemy interpretaría `postgresql://` a secas como psycopg2, que no está instalado.
2. **Render**: crea un Blueprint apuntando a este repositorio. `render.yaml` define el servicio; Render genera `SECRET_KEY` por su cuenta.
3. Rellena en el panel de Render los dos secretos marcados como `sync: false`:
   - `DATABASE_URL` — la cadena de Neon.
   - `ADMIN_PASSWORD_HASH` — el hash, **sin** duplicar los `$`. Ese escape solo hace falta en `.env`, que lo lee Docker Compose.
4. **GitHub**: en `Settings > Secrets and variables > Actions`, añade:
   - `RENDER_DEPLOY_HOOK_URL` — el hook de despliegue, en Render bajo `Settings > Deploy Hook`.
   - `DATABASE_URL` — la misma cadena de Neon, para la copia semanal del banco.

No hay paso de migración manual: `docker-start.sh` ejecuta `flask db upgrade` y `flask db-seed` antes de ceder el proceso a gunicorn. El plan gratuito no tiene comando de pre-despliegue, así que va ahí. Ambos son idempotentes; reiniciar no duplica nada ni pisa las preguntas importadas.

### Cómo se despliega

`render.yaml` lleva `autoDeployTrigger: "off"` a propósito: empujar a `main` no despliega nada por sí solo. El workflow `.github/workflows/ci.yml` construye la imagen, la arranca contra un Postgres real, comprueba que migra, siembra, deja entrar y protege las rutas, y solo entonces llama al hook de despliegue. Si la batería falla, a producción no llega nada.

### Copia de seguridad del banco

`.github/workflows/copia-del-banco.yml` exporta el banco desde producción cada lunes y lo versiona en `data/questions.backup.json`. Una vez desplegado, las preguntas viven solo en una base de Neon del plan gratuito, que no tiene recuperación a un punto en el tiempo: esta copia es la red. Se puede lanzar a mano desde la pestaña Actions. Si la exportación viene vacía, el workflow falla en vez de sobrescribir la copia buena.

## Preguntas nuevas

Se generan en el chat con la skill `preguntas-aib-c01` y se cargan pegando el JSON en la pantalla de importación, o con:

```bash
flask questions import fichero.json
```

Exporta el banco con regularidad y versiona el resultado: es el único contenido irreemplazable del repositorio.
