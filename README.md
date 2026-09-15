# Entrenador AIB-C01

Herramienta personal de preparación para la certificación AWS Certified AI Business Strategist (AIB-C01). Un solo usuario.

## Estado

Andamiaje. El código de la aplicación aún no existe: están el contexto (`CLAUDE.md`), la especificación (`SPEC.md`), el banco de preguntas y el prototipo de referencia.

## Estructura

```
CLAUDE.md                          contexto permanente y decisiones tomadas
SPEC.md                            qué construir, por fases
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

## Despliegue

Render, plan gratuito, con base de datos Postgres externa (Neon). Los servicios gratuitos de Render tienen sistema de archivos efímero y sus bases Postgres caducan a los 30 días: por eso la base va fuera. Variables de entorno necesarias: las de `.env.example`.

El servicio se duerme a los 15 minutos sin tráfico y tarda alrededor de un minuto en despertar.

## Preguntas nuevas

Se generan en el chat con la skill `preguntas-aib-c01` y se cargan pegando el JSON en la pantalla de importación, o con:

```bash
flask questions import fichero.json
```

Exporta el banco con regularidad y versiona el resultado: es el único contenido irreemplazable del repositorio.
