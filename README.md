# Entrenador AIB-C01

Herramienta personal de preparación para la certificación AWS Certified AI Business Strategist (AIB-C01). Un solo usuario.

## Estado

Fase 1 completa: acceso, banco de preguntas, los cuatro modos de práctica, importación con vista previa y exportación. La interfaz sigue el lenguaje visual de macOS, con modo claro y oscuro automáticos.

## Estructura

```
CLAUDE.md                          contexto permanente y decisiones tomadas
SPEC.md                            qué construir, por fases
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

## Despliegue

Render, plan gratuito, con base de datos Postgres externa (Neon). Los servicios gratuitos de Render tienen sistema de archivos efímero y sus bases Postgres caducan a los 30 días: por eso la base va fuera. Variables de entorno necesarias: las de `.env.example`.

El servicio se duerme a los 15 minutos sin tráfico y tarda alrededor de un minuto en despertar.

## Preguntas nuevas

Se generan en el chat con la skill `preguntas-aib-c01` y se cargan pegando el JSON en la pantalla de importación, o con:

```bash
flask questions import fichero.json
```

Exporta el banco con regularidad y versiona el resultado: es el único contenido irreemplazable del repositorio.
