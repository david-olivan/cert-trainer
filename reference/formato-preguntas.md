# Formato del JSON de importación

Es el formato que produce la skill `preguntas-aib-c01` y el que usa `data/questions.seed.json`. Las claves son cortas porque nacieron embebidas en el prototipo; al importarlas se mapean a los nombres largos del modelo `Question`.

```json
{
  "id":  "d2-13",
  "dom": 2,
  "hab": "2.1.3",
  "t":   "s",
  "q":   "Enunciado con el escenario y la pregunta.",
  "o":   ["Opción A", "Opción B", "Opción C", "Opción D"],
  "ok":  [0],
  "w":   "Explicación de por qué es correcta y por qué atrae el distractor principal.",
  "h":   "Pista que orienta el razonamiento sin desvelar la respuesta."
}
```

| Clave | Modelo | Notas |
|---|---|---|
| `id` | `ext_id` | Único. Prefijo `d<dominio>-` y número |
| `dom` | `domain` | 1 a 4 |
| `hab` | `skill` | Código de habilidad de la guía oficial |
| `t` | `type` | `s` respuesta única, `m` respuesta múltiple |
| `q` | `stem` | Escenario y pregunta |
| `o` | `options` | 4 opciones en las de tipo `s`, 5 en las de tipo `m` |
| `ok` | `correct` | Índices base 0. Dos elementos en las de tipo `m` |
| `w` | `explanation` | Se muestra tras responder |
| `h` | `hint` | Opcional, bajo demanda antes de responder |

## Estado del banco sembrado

44 preguntas: 11 del dominio 1, 12 del 2, 10 del 3, 11 del 4. Solo 4 son de respuesta múltiple, alrededor de una de cada once, cuando la proporción objetivo es una de cada seis. Es el primer hueco que conviene cubrir al generar preguntas nuevas.

Cada pregunta cubre una habilidad distinta, así que ninguna habilidad tiene todavía más de un enunciado: el banco da cobertura amplia y poca profundidad.
