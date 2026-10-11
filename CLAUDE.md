# CLAUDE.md

Contexto permanente de este repositorio. Léelo antes de tocar nada.

## Qué es esto

Un entrenador personal para la certificación **AWS Certified AI Business Strategist (AIB-C01)**. Aplicación Flask con un único usuario: el dueño del repositorio. Desde la fase 2 admite cualquier examen tipo test, con AIB-C01 como el primero y el prioritario. No es un producto, no habrá registro de usuarios, no habrá multiusuario. Cualquier propuesta que asuma varios usuarios está fuera de alcance salvo que se pida explícitamente.

El examen está en beta desde el 29 de septiembre de 2026 y la insignia de Early Adopter exige certificarse antes del **15 de febrero de 2027**. Esa es la fecha límite real del proyecto: las decisiones de alcance se resuelven a favor de lo que se pueda usar para estudiar esta semana.

## Estado de partida

- `reference/entrenador-artefacto.html` — prototipo funcional en un solo archivo, hecho como artefacto de chat. **Es referencia, no código a copiar.** La lógica de sesiones, el muestreo ponderado por dominio y el diseño visual valen; su persistencia no, porque usa `window.storage`, una API que solo existe en el entorno de artefactos.
- `data/questions.seed.json` — 44 preguntas originales, el contenido con más valor del repositorio. Formato documentado en `reference/formato-preguntas.md`.
- `SPEC.md` — qué hay que construir y en qué orden.

## Decisiones ya tomadas

No las reabras sin motivo nuevo; si crees que alguna está mal, dilo antes de implementar otra cosa.

| Decisión | Motivo |
|---|---|
| Flask + SQLAlchemy | Simplicidad; el autor conoce el stack |
| SQLite en local, Postgres en producción | El plan gratuito de Render tiene sistema de archivos efímero: un SQLite local se pierde en cada redespliegue |
| Base de datos gestionada externa (Neon) | Las bases gratuitas de Render caducan a los 30 días |
| Flask-Login con un usuario sembrado desde variables de entorno | Un solo usuario: sobra la tabla `users` con registro, pero sí hay modelo `User` por si algún día se comparte |
| Frontend server-side con Jinja y JavaScript sin framework | El prototipo ya funciona así; añadir React multiplicaría el trabajo sin beneficio |
| Docker + gunicorn | Despliegue reproducible; `docker-compose.yml` es solo para desarrollo local |
| Despliegue en Render, plan gratuito | Coste cero; el arranque en frío de un minuto es aceptable para sesiones de estudio |
| Repetición espaciada con FSRS (librería `fsrs`), no Leitner | Predice la probabilidad de acierto de cada pregunta, y esa predicción se puede medir y ajustar con el historial propio. Sustituye a lo que pedía la antigua `SPEC.md` 2.4 |
| El optimizador de FSRS corre en GitHub Actions, nunca en la imagen | Necesita torch, que no cabe en los 512 MB de la instancia gratuita de Render. `fsrs[optimizer]` va en un `requirements-optimizer.txt` aparte |

## Ponderación del examen

Las tandas se muestrean respetando el peso oficial de cada dominio. Hoy vive en `app/sampling.py` y está repetido en el JavaScript y en el validador. Con el modelo de varios exámenes (hito 1 de la fase 2) pasa a la base de datos, que será el único punto de verdad: no vuelvas a escribir dominios ni pesos en el código.

| Dominio | Nombre | Peso |
|---|---|---|
| 1 | Conceptos básicos y alfabetización en IA | 24 % |
| 2 | Estrategia de IA y creación de valor empresarial | 28 % |
| 3 | Gobernanza de la IA y liderazgo responsable | 24 % |
| 4 | Preparación empresarial, liderazgo y transformación | 24 % |

El examen puntúa de 100 a 1000 y aprueba en 700, pero no publica el porcentaje de aciertos equivalente. La aplicación usa **72 % como umbral orientativo** y debe presentarlo siempre como estimación, nunca como predicción de resultado.

## Reglas del examen que la aplicación debe respetar

- Las preguntas de respuesta múltiple exigen acertar **todas** las opciones correctas: no hay crédito parcial.
- No hay penalización por fallar, así que una pregunta en blanco cuenta como error. Si se añade navegación libre, avisar de las preguntas sin contestar antes de cerrar un simulacro.
- Duración oficial en la guía: 130 minutos. La página del beta indica 170. La aplicación calcula el tiempo a razón de dos minutos por pregunta.

## Cómo trabajar aquí

- Todo el texto que ve el usuario, en español de España. Los identificadores del código, en inglés.
- Los mensajes de error explican qué ha pasado y cómo arreglarlo. Nada de «Ha ocurrido un error».
- Antes de dar por buena una tarea, comprueba que la aplicación arranca con `docker compose up` y que el flujo completo (entrar, responder una tanda, ver el resultado, volver) funciona.
- No añadas dependencias sin decir qué problema resuelven.
- Las preguntas nuevas las genera Claude en el chat con la skill `preguntas-aib-c01` y entran por la utilidad de importación. Para otros exámenes, con el kit exportable de la fase 2 pegado en el chat. **Nunca generes preguntas dentro de este repositorio ni edites las existentes por tu cuenta**: el banco es contenido curado, no datos de prueba.

## Ramas

- **Nunca se trabaja sobre `main`.** Está protegida y cada push a ella despliega en producción. Todo cambio, por pequeño que sea, va en una rama nueva creada desde `main` actualizada y entra por pull request.
- Nombre de rama: `<tipo>/<issue>-<descripcion-corta>`, por ejemplo `feat/7-modelo-certificaciones` o `fix/12-portada-500`. Sin issue, se omite el número. Las sesiones de Claude Code en la nube trabajan en la rama `claude/…` que les asigna el entorno: vale igual, la regla es no tocar `main`.
- Una rama por issue o por cambio coherente. Si el PR de una rama ya se mergeó, el trabajo siguiente va en una rama nueva o en la misma reiniciada desde `main`, nunca apilado encima de lo ya mergeado.
- La rama se borra al mergear el PR.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/), en español:

```
<tipo>(<ámbito opcional>): <resumen en infinitivo, en minúscula, sin punto final>

Cuerpo: qué cambia y, sobre todo, por qué. Líneas de unos 72 caracteres.
Lo que no se deduce del diff: alternativas descartadas, medidas tomadas,
lo que se ha comprobado.

Closes #7
```

- Tipos: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`, `chore`.
- Resumen como en el historial: `feat: resolver la tanda con el teclado`, `fix: la portada devolvía 500 en Postgres`.
- Un cambio incompatible (de esquema, de formato de importación) lleva `!` tras el tipo y un pie `BREAKING CHANGE:` que diga qué hay que hacer.
- **Sin líneas de atribución**: ni `Co-Authored-By`, ni `Claude-Session`, ni similares. Vale también para los commits que haga Claude.

## Issues

- El trabajo nace de un issue. Si no lo hay y el cambio no es trivial, se abre antes de empezar.
- Se vinculan desde el pie del commit o desde la descripción del PR con las palabras clave **en inglés**: `Closes #7`, `Fixes #12`. GitHub solo reconoce esas: «Cierra #5» enlaza el issue pero no lo cierra. Para un commit que avanza un issue sin terminarlo, `Refs #7`.
- El issue se cierra solo cuando el PR llega a `main`, no antes.
- El PR lleva título en formato de commit convencional y, en la descripción, qué cambia, por qué, `Closes #N` y cómo se ha comprobado.

## Despliegue

Solo despliega `main`, y solo a través de CI: `render.yaml` tiene `autoDeployTrigger: "off"`. El recorrido de un cambio:

1. Push a la rama: el workflow CI corre `pruebas` (pytest contra Postgres) e `imagen` (construye la imagen, la arranca como en producción y comprueba acceso y banco). No despliega.
2. PR a `main`: CI vuelve a correr. No se mergea en rojo.
3. Merge: el push a `main` relanza CI y, si sale verde, el job `desplegar` llama al hook de Render.
4. Render construye la imagen y `docker-start.sh` ejecuta `flask db upgrade` y `flask db-seed` antes de arrancar gunicorn. Comprobar `/healthz` y entrar.

Cada cambio de esquema lleva su migración de Alembic en el mismo PR: generarla con `flask db migrate -m "…"`, revisarla a mano y probarla contra Postgres con `TEST_DATABASE_URL`. Si la migración transforma datos existentes, antes de mergear se lanza a mano el workflow «Copia del banco» para tener el banco de producción versionado.

Para redesplegar sin cambiar código: botón **Run workflow** del workflow CI sobre `main`. La puesta en marcha inicial (Neon, Render, secretos de GitHub) está en el README.
