# SPEC.md — qué construir

Orden recomendado: fase 1 completa y usable antes de tocar la fase 2. El criterio de «usable» es que el dueño pueda estudiar con ello esa misma tarde.

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

## Fase 2 — Lo que lo convierte en una herramienta de estudio

### 2.1 Marcar preguntas y navegación libre en el simulacro

El examen real permite marcar una pregunta y volver a ella. Practicar esa gestión del tiempo es parte de lo que se entrena. Requiere navegación no lineal y un aviso de preguntas sin responder antes de cerrar.

### 2.2 Tiempo por pregunta

Ya se guarda en `Attempt`. Explótalo: una pregunta acertada tras noventa segundos de duda no es conocimiento consolidado, y esa señal no aparece en el porcentaje de aciertos. Muéstrala en el resultado.

### 2.3 Cobertura por habilidad

La guía define unas 45 habilidades (lista en `reference/dominios-y-habilidades.md`, incluido en la skill). Una vista que muestre cuáles no tienen ninguna pregunta todavía y cuáles se fallan de forma repetida convierte la generación de preguntas nuevas en algo dirigido en lugar de aleatorio. Es la función con mejor relación entre esfuerzo y valor de toda la fase 2.

### 2.4 Repetición espaciada ligera

En lugar de un repaso de fallos plano, reprogramar la reaparición de lo fallado a 1, 3 y 7 días. Un Leitner de tres cajas basta; no hace falta SM-2.

### 2.5 Notas propias por pregunta

Un campo de texto libre que persiste junto a la pregunta, visible al repasarla. Es el cuaderno de errores de toda la vida y es la parte que más rinde de cualquier preparación de examen.

---

## Deuda técnica conocida

Ninguna rompe nada hoy. Están aquí para que, cuando toquen, no haya que diagnosticarlas desde cero.

### El aviso de `get_engine()` en las migraciones es ruido, no deuda

Cada vez que corren las migraciones sale un `DeprecationWarning`: `migrations/env.py` llama a `db.get_engine()`, que Flask-SQLAlchemy retira en la versión 3.2. **No hay nada que arreglar.** Es el `env.py` que genera Flask-Migrate y ya trae un `try/except` que cae a `db.engine` cuando la primera llamada falla, que es justo lo que pasará al subir a 3.2.

Queda apuntado para que nadie vuelva a investigarlo al verlo en los registros de CI ni «lo arregle» tocando código generado.

### La cola de la tanda viaja en la cookie de sesión

`app/api.py` guarda en la sesión de Flask la lista de preguntas, el reordenamiento de opciones de cada una y los resultados. Está bien decidido —así el JavaScript no puede leer la respuesta correcta inspeccionando la red—, pero la sesión de Flask es una cookie firmada, y los navegadores cortan las cookies en 4 KB.

Lo que importa es que el simulacro muestrea *todas* las preguntas activas, así que la cookie crece con el banco sin que nadie lo decida. Medido con el serializador real de Flask y con `ext_id` del formato que se usa (`d1-01`), que Flask comprime con zlib antes de firmar:

| Preguntas en el banco | Tamaño de la cookie |
|---|---|
| 44 (hoy) | 623 B |
| 200 | 1,9 kB |
| 400 | 3,6 kB |
| 444 | ~4 kB, el límite |

O sea: hay sitio de sobra y el problema no es para mañana. Se apunta porque el día que llegue no avisa — el navegador descarta la cookie en silencio y el síntoma es un simulacro que sale en blanco o que pierde la sesión a mitad, no un error que diga qué pasa.

Cuando el banco pase de las 300 preguntas, mover el estado de la cola a una tabla, referenciada desde la sesión por el `id` de `StudySession`, que ya existe. Para reproducir la medición: serializar el diccionario que arma `/api/session/start` con `SecureCookieSessionInterface` y mirar cuánto ocupa.

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
