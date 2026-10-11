# Entrenador de certificaciones

[![CI](https://github.com/david-olivan/cert-trainer/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/david-olivan/cert-trainer/actions/workflows/ci.yml)
[![Copia del banco](https://github.com/david-olivan/cert-trainer/actions/workflows/copia-del-banco.yml/badge.svg?branch=main)](https://github.com/david-olivan/cert-trainer/actions/workflows/copia-del-banco.yml)

Entrenador personal para exámenes tipo test, hecho para preparar la certificación **AWS Certified AI Business Strategist (AIB-C01)**, que sigue siendo el examen prioritario. Aplicación Flask de un solo usuario, desplegada en Render con la base en Neon.

## Qué hace

- **Acceso** de un único usuario (`admin` por defecto, o el de `ADMIN_USERNAME`) con sesión recordada 30 días y bloqueo temporal tras cinco intentos fallidos.
- **Varios exámenes.** Dominios, pesos, formatos de pregunta, umbral orientativo y minutos por pregunta viven en la base (tablas `exams`, `domains` y `question_formats`). AIB-C01 lo crea una migración y hoy es el examen sobre el que se trabaja.
- **Modos de práctica**, siempre ponderados por el peso de cada dominio y con el orden de las opciones aleatorizado:
  - **Repaso de hoy**: repetición espaciada con FSRS. Primero las preguntas vencidas, de menor a mayor probabilidad de acierto, y después un cupo diario de nuevas. Ninguna revisión se programa después de la fecha del examen.
  - **Simulacro cronometrado**: todas las preguntas, a los minutos por pregunta del examen, sin explicaciones hasta el final.
  - **Tanda rápida** de diez preguntas.
  - **Por dominio**.
- **Señales de cada respuesta**: «Comprobar · seguro» o «Comprobar · dudo», si se usó la pista, el tiempo y el orden de opciones mostrado. Alimentan la nota FSRS y las métricas futuras.
- **Modo «primero piensa»**: enunciado solo, y las opciones cuando se piden. No se aplica al simulacro.
- **Medidor de preparación por dominio** en la portada, con el umbral orientativo del examen (72 % en AIB-C01). Es una estimación, nunca una predicción del resultado.
- **Banco de preguntas** con importación (vista previa obligatoria y validación contra los dominios y formatos del examen) y exportación a JSON, desde `/preguntas` o por consola.

Lo que falta y en qué orden está en [`SPEC.md`](SPEC.md) y en la épica [#12](https://github.com/david-olivan/cert-trainer/issues/12).

## Arranque local

```bash
cp .env.example .env        # y rellena SECRET_KEY y ADMIN_PASSWORD_HASH
docker compose up --build
```

La aplicación queda en `http://localhost:8000`. Al arrancar, `docker-entrypoint.sh` aplica las migraciones, siembra el usuario y el banco y reconstruye el estado FSRS. La base local es un SQLite en `data/app.db`.

Para generar el hash de la contraseña:

```bash
python -c "from werkzeug.security import generate_password_hash as g; print(g(input('contraseña: ')))"
```

**Importante al pegarlo en `.env`:** el hash de scrypt lleva `$` como separador (`scrypt:N:r:p$sal$hash`). Docker Compose interpola `$NOMBRE` dentro de los valores de `env_file`, así que cada `$` del hash debe escaparse como `$$` en `.env`; si no, Compose lo trunca en silencio y el acceso falla (con un hash mal formado del todo, puede dar incluso un error 500 en vez de «Usuario o contraseña incorrectos»). Duplica cada `$` a mano antes de guardar el archivo.

Si el acceso sigue fallando después de reconstruir, comprueba que no haya otro proceso escuchando en el puerto 8000 (`netstat -ano | findstr ":8000"` en Windows): un `flask run` suelto fuera de Docker, apuntando al mismo `data/app.db`, puede interceptar las peticiones y confundir el diagnóstico.

Variables opcionales: `ADMIN_USERNAME` (por defecto `admin`) y `TIMEZONE` (por defecto `Europe/Madrid`), que decide dónde acaba «hoy» para el repaso diario.

### Datos de demostración

Con la base recién sembrada todas las pantallas salen vacías. Para revisar la interfaz con datos realistas:

```bash
flask db-seed-demo          # genera 6 sesiones y sus intentos sintéticos
flask db-seed-demo --reset  # los regenera, borrando el progreso anterior
flask db-reset-progress     # borra todo el progreso y deja la base limpia
```

La semilla es fija: dos ejecuciones producen exactamente los mismos datos y las capturas de pantalla son comparables. El perfil está pensado para que cada dominio caiga en un estado distinto del medidor. Estos comandos solo tocan el progreso (sesiones, intentos y estado FSRS): **el banco de preguntas no se toca nunca**. El mismo borrado está en el botón «Reiniciar» de la barra superior.

### Repetición espaciada

Cada respuesta es una revisión FSRS: se traduce a una nota según el acierto, la confianza, la pista y el tiempo, y actualiza cuándo toca volver a ver la pregunta. El estado vive en `review_states` y se deriva entero de `attempts`, así que se puede rehacer en cualquier momento:

```bash
flask fsrs rebuild
```

Es idempotente y el arranque lo lanza siempre (`docker-start.sh` y `docker-entrypoint.sh`). La lógica y los umbrales están en `app/srs.py`.

### Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

Comprueban sobre todo lo que rompe un despliegue (la cadena de conexión, las migraciones, la siembra, el acceso y las rutas protegidas), además de FSRS, el repaso de hoy, las señales, «primero piensa» y el modelo de varios exámenes. Por defecto corren contra un SQLite desechable; para correrlas contra Postgres, exporta `TEST_DATABASE_URL`. En CI corren siempre contra Postgres y fallan si falta esa variable.

## Preguntas nuevas

Las preguntas de AIB-C01 se generan en el chat con la skill `preguntas-aib-c01` y se cargan pegando el JSON en la pantalla de importación (`/preguntas`), con vista previa de lo que entra y lo que se descarta, o por consola:

```bash
flask questions import fichero.json
flask questions export banco.json
```

El formato está en [`reference/formato-preguntas.md`](reference/formato-preguntas.md). Las preguntas no se generan ni se editan dentro del repositorio: el banco es contenido curado y el único irreemplazable del proyecto.

## Despliegue

Render, plan gratuito, con la base Postgres fuera, en Neon: los servicios gratuitos de Render tienen sistema de archivos efímero y sus bases Postgres caducan a los 30 días. El servicio se duerme a los 15 minutos sin tráfico y tarda alrededor de un minuto en despertar; es el precio del plan gratuito y está asumido.

### Puesta en marcha, una sola vez

1. **Neon**: crea un proyecto en `eu-central-1` (la región de Fráncfort, donde va el servicio) y copia la cadena de conexión. Se pega tal cual: `app/config.py` la reescribe a `postgresql+psycopg://` al arrancar, porque SQLAlchemy interpretaría `postgresql://` a secas como psycopg2, que no está instalado.
2. **Render**: crea un Blueprint apuntando a este repositorio. `render.yaml` define el servicio; Render genera `SECRET_KEY` por su cuenta.
3. Rellena en el panel de Render los dos secretos marcados como `sync: false`:
   - `DATABASE_URL`: la cadena de Neon.
   - `ADMIN_PASSWORD_HASH`: el hash, **sin** duplicar los `$`. Ese escape solo hace falta en `.env`, que lo lee Docker Compose.
4. **GitHub**, en `Settings > Secrets and variables > Actions`:
   - `RENDER_DEPLOY_HOOK_URL`: el hook de despliegue, en Render bajo `Settings > Deploy Hook`.
   - `DATABASE_URL`: la misma cadena de Neon, para la copia semanal del banco.
5. **GitHub**, en `Settings > General > Pull Requests`: activa «Automatically delete head branches» para que las ramas se borren solas al mergear.

No hay paso de migración manual: `docker-start.sh` ejecuta `flask db upgrade`, `flask db-seed` y `flask fsrs rebuild` antes de ceder el proceso a gunicorn. El plan gratuito no tiene comando de pre-despliegue, así que va ahí. Los tres son idempotentes: reiniciar no duplica nada ni pisa las preguntas importadas.

### Cómo se despliega

Solo despliega `main`, y solo a través de CI: `render.yaml` lleva `autoDeployTrigger: "off"`, así que empujar a `main` no despliega nada por sí solo. El workflow [`ci.yml`](.github/workflows/ci.yml) tiene tres jobs:

- **Pruebas**: `pytest` contra un Postgres real.
- **Imagen**: construye la imagen, la arranca como en producción y comprueba que migra, siembra, deja entrar, protege las rutas y tiene el banco cargado.
- **Desplegar**: solo en `main` y solo si los dos anteriores salen en verde, llama al hook de Render.

El recorrido de un cambio: rama nueva desde `main` → push (CI corre, no despliega) → pull request a `main` (no se mergea en rojo) → merge (CI vuelve a correr y despliega) → Render construye la imagen y `docker-start.sh` migra y siembra. Después, comprueba `/healthz` y entra.

Si el PR trae una migración que transforma datos, lanza antes a mano el workflow «Copia del banco».

Para **redesplegar sin cambiar código** (tras actualizar el secreto del hook, o para reintentar un despliegue que se quedó a medias en Render): botón **Run workflow** del workflow CI en la pestaña Actions, eligiendo `main`. Vuelve a correr la batería entera antes de llamar al hook y no hace falta ningún commit vacío.

### Copia de seguridad del banco

[`copia-del-banco.yml`](.github/workflows/copia-del-banco.yml) exporta el banco desde producción cada lunes y lo versiona en `data/questions.backup.json`. Una vez desplegado, las preguntas viven solo en una base de Neon del plan gratuito, sin recuperación a un punto en el tiempo: esta copia es la red. Se puede lanzar a mano desde la pestaña Actions. Si la exportación viene vacía, el workflow falla en vez de sobrescribir la copia buena.

## Estructura

```
CLAUDE.md                     contexto, decisiones tomadas y normas de trabajo
SPEC.md                       qué construir, por fases, y deuda técnica conocida
app/                          la aplicación Flask
  models.py                   exámenes, dominios, formatos, preguntas, intentos, estado FSRS
  srs.py                      repetición espaciada (FSRS) y repaso de hoy
  sampling.py                 muestreo ponderado por dominio y medidor de preparación
  import_validation.py        validador único de la importación (web y consola)
  cli.py                      comandos flask: questions, db-seed, db-seed-demo, db-reset-progress, fsrs
  templates/                  plantillas Jinja
  static/                     CSS (tokens de diseño) y JavaScript sin framework
migrations/                   migraciones de Alembic
tests/                        pruebas (pytest)
data/questions.seed.json      preguntas originales de AIB-C01 (contenido curado)
reference/                    prototipo original y formato del JSON de importación
Dockerfile, docker-start.sh   imagen y arranque de producción
docker-compose.yml            solo para desarrollo local
render.yaml                   el servicio de Render (la base va aparte, en Neon)
.github/workflows/            CI con despliegue y copia del banco
```

## Cómo se trabaja

Las normas completas están en [`CLAUDE.md`](CLAUDE.md). En corto: nunca se trabaja sobre `main`; cada cambio va en su rama (`<tipo>/<issue>-<descripcion>`) y entra por pull request; los commits siguen [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) en español y sin líneas de atribución; los issues se cierran con `Closes #N` en inglés, que es lo único que GitHub reconoce. Cada cambio de esquema lleva su migración en el mismo PR.
