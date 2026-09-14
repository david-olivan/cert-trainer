# CLAUDE.md

Contexto permanente de este repositorio. Léelo antes de tocar nada.

## Qué es esto

Un entrenador personal para la certificación **AWS Certified AI Business Strategist (AIB-C01)**. Aplicación Flask con un único usuario: el dueño del repositorio. No es un producto, no habrá registro de usuarios, no habrá multiusuario. Cualquier propuesta que asuma varios usuarios está fuera de alcance salvo que se pida explícitamente.

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

## Ponderación del examen

Las tandas se muestrean respetando el peso oficial de cada dominio. Está codificado en varios sitios: mantenlo en un único punto de verdad.

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
- Las preguntas nuevas las genera Claude en el chat con la skill `preguntas-aib-c01` y entran por la utilidad de importación. **Nunca generes preguntas dentro de este repositorio ni edites las existentes por tu cuenta**: el banco es contenido curado, no datos de prueba.
