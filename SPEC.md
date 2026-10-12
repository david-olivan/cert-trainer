# SPEC.md — qué construir

Orden recomendado: fase 1 completa y usable antes de tocar la fase 2. El criterio de «usable» es que el dueño pueda estudiar con ello esa misma tarde. La fase 1 está terminada y desplegada.

---

## Fase 1 — Lo mínimo que sirve para estudiar

### 1.1 Pantalla de acceso

Un único usuario. Formulario con contraseña (el correo o nombre de usuario es opcional, decide lo que resulte menos fricción en móvil) contra un hash guardado en variable de entorno, sesión con Flask-Login y cookie firmada. Todo lo demás exige sesión iniciada.

Requisitos que no son opcionales:

- `SECRET_KEY` desde el entorno; si falta, la aplicación no arranca, no genera una aleatoria en silencio.
- Cookies `Secure`, `HttpOnly` y `SameSite=Lax`; redirección a HTTPS en producción.
- Limitación de intentos de acceso: bloqueo temporal tras varios fallos. Está expuesto a internet.
- «Recordar sesión» con caducidad larga, porque el uso es diario desde los mismos dos dispositivos y teclear la contraseña en el móvil cada vez es el tipo de fricción que hace abandonar una herramienta de estudio.
- `robots.txt` con `Disallow: /` y cabecera `noindex`.

### 1.2 Modelo de datos

- `User` — un solo registro, sembrado desde el entorno. Existe para no tener que rehacer el esquema si algún día se comparte.
- `Question` — `ext_id` (el `id` del JSON, con restricción de unicidad), `domain`, `skill`, `type`, `stem`, `options` (JSON), `correct` (JSON), `explanation`, `hint`, `created_at`, `source` (`seed` o `import`), `active`.
- `Attempt` — un registro por pregunta respondida: `question_id`, `session_id`, `selected` (JSON), `is_correct`, `seconds_spent`, `answered_at`. Es la tabla que sostiene toda la analítica; no la simplifiques a un contador de aciertos.
- `StudySession` — `mode`, `started_at`, `finished_at`, `question_count`, `score_pct`.

Migraciones con Alembic desde el principio. El banco es contenido curado y no quiero recrear la base para añadir una columna.

### 1.3 Modos de práctica

Los cuatro del prototipo: simulacro cronometrado a dos minutos por pregunta, tanda rápida de diez, entrenamiento por dominio y repaso de fallos. El muestreo general respeta la ponderación oficial.

Dos cosas que el prototipo no hace y que sí debe hacer esta versión:

- **Aleatorizar el orden de las opciones** en cada presentación. Con un banco pequeño que se repite, memorizar la posición de la respuesta es el fallo de diseño más probable de todo el proyecto.
- **Guardar cada respuesta al responderla**, no al terminar la tanda. En el prototipo, abandonar a mitad perdía la sesión entera.

### 1.4 Utilidad de carga de preguntas

Las preguntas nuevas se generan en el chat con la skill `preguntas-aib-c01` y llegan como un array JSON. Hace falta una pantalla, accesible solo con sesión iniciada, con un área de texto donde pegarlo.

- **Validación antes de insertar**: estructura correcta, dominio entre 1 y 4, índices de `correct` dentro del rango de `options`, dos correctas en las de tipo múltiple, `ext_id` no repetido.
- **Vista previa obligatoria**: qué entra, qué se descarta y por qué, con la pregunta renderizada como se verá. Después se confirma. Nada de importar a ciegas.
- **Idempotencia**: reimportar el mismo bloque no duplica nada.
- El mismo validador debe estar disponible como comando de consola (`flask questions import fichero.json`) para poder sembrar y hacer copias de seguridad sin navegador.
- **Exportar el banco completo** a JSON desde la misma pantalla. Es la copia de seguridad del único contenido irreemplazable del proyecto, y debe poder versionarse en el repositorio.

### 1.5 Interfaz

Parte de `reference/entrenador-artefacto.html`: el medidor de preparación por dominio como elemento principal, el enunciado en serif, las opciones con letra, el veredicto con la explicación y la habilidad de la guía. Conviértelo a plantillas Jinja y llamadas a la API.

Se usa sobre todo desde el móvil: comprueba el diseño a 380 px antes de darlo por bueno.

---

## Fase 2 — Varios exámenes, repetición espaciada y métricas

Épica: #12. La fase 1 está completa y en producción.

La aplicación deja de estar atada a AIB-C01: cualquier examen tipo test se da de alta con sus dominios, pesos y formatos de pregunta, y se estudia con repetición espaciada FSRS. Cada respuesta deja las señales necesarias para medir el algoritmo y ajustarlo con datos propios.

AIB-C01 sigue siendo la prioridad, porque la fecha límite real es el 15 de febrero de 2027. Por eso el orden va primero a lo que sirve para estudiarlo, y las pantallas de gestión de exámenes vienen después del repaso espaciado.

### Decisiones de esta fase

- **FSRS en lugar de Leitner.** La versión anterior de este documento pedía «un Leitner de tres cajas; no hace falta SM-2». Se cambia porque el objetivo es ajustar el algoritmo con métricas, y eso exige que prediga algo medible. FSRS estima la probabilidad de acertar cada pregunta en cada momento; esa predicción se compara con el resultado real (calibración, log loss). Leitner no predice nada que se pueda contrastar. Se usa la librería `fsrs` (MIT, sin dependencias pesadas).
- **El optimizador corre en GitHub Actions.** Ajustar los parámetros de FSRS a un historial propio necesita torch, que no cabe en la instancia gratuita de Render (512 MB de RAM). Un workflow, como el de la copia del banco, lee el historial de Neon, optimiza y guarda los parámetros nuevos solo si mejoran a los vigentes. Por debajo de 512 revisiones no hay nada que ajustar: se usan los parámetros por defecto, que ya funcionan bien.
- **Una pregunta tipo test no es recuerdo activo puro.** Repetirla mide, en parte, que recuerdas *esa pregunta*. Dos contrapesos: el modo «primero piensa» (enunciado antes que opciones) y el **acierto en primera vista** como indicador principal de preparación.

### Hito 0 — Señales y recuerdo activo

- **Confianza, pista y orden de opciones en cada respuesta** (#13). «Comprobar · seguro» y «Comprobar · dudo» sustituyen al botón actual; se guarda también si se usó la pista y la permutación de opciones mostrada. Va primero porque cada día sin estas señales es historial que el optimizador no podrá usar.
- **Modo «primero piensa»** (#14). Enunciado solo, tecla para mostrar las opciones. No aplica al simulacro.

### Hito 1 — Modelo de varios exámenes

- **Modelo** (#7): `Exam`, `Domain`, `Skill` (opcional) y `QuestionFormat`. Un formato es un par «opciones / correctas»: AIB-C01 tiene 4/1 y 5/2. La migración crea AIB-C01 con los datos de hoy y reasigna el banco. Antes de mergearla, copia del banco a mano.
- **Fuera los dominios fijos** (#15). Pesos, nombres, 1..4, `s`/`m` y el 72 % dejan de estar repetidos en Python, plantillas y JavaScript: el único punto de verdad pasa a ser la base de datos.

### Hito 2 — Repetición espaciada

- **FSRS por pregunta** (#16). Un estado FSRS por pregunta y parámetros por examen. Cada respuesta se traduce a una nota FSRS: fallo → Again; acierto con duda, con pista o lento → Hard; acierto seguro → Good; seguro y rápido → Easy. Los umbrales de «lento» y «rápido» son configurables: son los primeros mandos que ajustar. Ninguna revisión se programa después de la fecha de examen. `flask fsrs rebuild` reconstruye los estados desde el historial.
- **«Repaso de hoy»** (#17) sustituye a «Repaso de fallos»: primero las vencidas, de menor a mayor probabilidad de acierto, y después un cupo diario de nuevas con el peso de cada dominio.
- **La cola sale de la cookie** (#18). Resuelve la deuda técnica de más abajo antes de que el banco crezca.

### Hito 3 — Gestión de exámenes

- **CRUD de exámenes** (#19): dominios con pesos que suman 100, formatos permitidos con su proporción objetivo, habilidades opcionales, fecha de examen, retención deseada. Archivar en vez de borrar cuando hay historial.
- **Examen activo en la portada** (#8).

### Hito 4 — Generación dirigida

- **Kit para Claude e importación por examen** (#20). Un Markdown exportable con instrucciones, ficha del examen, esquema JSON, huecos de cobertura e `id` ya usados, para pegarlo en el chat. Recoge la antigua 2.3 (cobertura por habilidad). La importación acepta `{"exam": "…", "questions": […]}` y valida contra los formatos del examen; el array pelado sigue valiendo.

### Hito 5 — Métricas y ajuste

- **Panel de métricas** (#21):
  - Acierto en primera vista.
  - Medidor de preparación basado en FSRS.
  - Fallos marcados como «seguro».
  - Tiempo por pregunta (recoge la antigua 2.2).
  - Cobertura.
  - Distractores más elegidos y sesgo de posición.
  - Proyección al día del examen, siempre presentada como estimación.

  Hecho en `/metricas` (`app/metrics.py`). El medidor mezcla las dos fuentes: probabilidad FSRS para las preguntas vistas y acierto en primera vista del dominio para las que no, porque una media solo de las vistas daría 95 % con una pregunta repasada. La proyección supone que no se repasa nada más: es un suelo. La carga prevista rehace la historia con los parámetros actuales, porque el vencimiento solo se guarda para el último repaso.
- **Evaluación del algoritmo** (#22):
  - Calibración, log loss y RMSE de la predicción de FSRS.
  - `flask fsrs replay` para comparar parámetros y umbrales sobre el historial real.
- **Optimizador** (#23): el workflow semanal o manual descrito arriba.

### Sueltas, cuando apetezca

No dependen de nada de lo anterior y siguen siendo valiosas:

- **Marcar preguntas y navegación libre en el simulacro.** El examen real permite marcar y volver; requiere navegación no lineal y aviso de preguntas sin responder antes de cerrar.
- **Notas propias por pregunta.** Texto libre visible al repasar: el cuaderno de errores de siempre.

---

## Deuda técnica conocida

Ninguna rompe nada hoy. Están aquí para que, cuando toquen, no haya que diagnosticarlas desde cero.

### El aviso de `get_engine()` en las migraciones es ruido, no deuda

Cada vez que corren las migraciones sale un `DeprecationWarning`: `migrations/env.py` llama a `db.get_engine()`, que Flask-SQLAlchemy retira en la versión 3.2. **No hay nada que arreglar.** Es el `env.py` que genera Flask-Migrate y ya trae un `try/except` que cae a `db.engine` cuando la primera llamada falla, que es justo lo que pasará al subir a 3.2.

Queda apuntado para que nadie vuelva a investigarlo al verlo en los registros de CI ni «lo arregle» tocando código generado.

### Resuelta: la cola de la tanda viajaba en la cookie de sesión

Hasta #18, `app/api.py` guardaba en la cookie de sesión de Flask la cola de la tanda, el reordenamiento de opciones y los resultados. Los navegadores descartan en silencio las cookies de más de 4 kB, y el simulacro mete todas las preguntas activas: hacia las 444 preguntas el simulacro habría salido en blanco sin ningún error.

Desde #18 la cola vive en `study_sessions` (`queue`, `option_orders`, `position`, `recall_first`) y la cookie solo lleva el id de la sesión. Hay una prueba que arma un simulacro de 500 preguntas y comprueba que la cookie sigue por debajo de 1 kB (`tests/test_cola.py`).

---

## Fuera de alcance

Registro de usuarios, recuperación de contraseña, roles, aplicación móvil nativa, generación de preguntas dentro de la aplicación, integración con la API de Anthropic, estadísticas comparativas con otros candidatos, gamificación con rachas o insignias.

---

## Comprobación antes de considerar terminada la fase 1

1. `docker compose up` levanta la aplicación en local con la base sembrada.
2. Sin sesión iniciada, cualquier ruta redirige al acceso.
3. Una tanda completa se responde, se guarda y aparece en el historial.
4. Cerrando el navegador a mitad de una tanda, las respuestas dadas siguen registradas.
5. La misma cuenta abierta en móvil y en portátil muestra el mismo historial.
6. Un bloque de preguntas con un error deliberado (índice de `correct` fuera de rango) se rechaza con un mensaje que dice qué pregunta y qué campo.
7. El despliegue en Render arranca y se conecta a la base externa.
