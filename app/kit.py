"""Kit para generar preguntas con Claude (issue #20).

Un bloque Markdown que se pega en una conversación con Claude: el encargo,
las reglas de redacción, la ficha del examen, dónde faltan preguntas y el
formato exacto que acepta la importación. La aplicación no genera
preguntas ni llama a ninguna API (CLAUDE.md): el kit solo hace que la
generación, que ocurre en el chat, vaya dirigida a lo que falta.
"""
import json
import re
from collections import Counter, defaultdict

from sqlalchemy import func

from app.extensions import db
from app.models import Attempt, Question

DEFAULT_COUNT = 20
MAX_COUNT = 100
EXT_ID = re.compile(r"^d(\d+)-(\d+)$")
WEAK_MIN_ATTEMPTS = 3  # por debajo, un porcentaje de fallos no dice nada


def largest_remainder(total, weights):
    """Reparte `total` en enteros proporcionales a `weights` ({clave: peso}) sin perder ninguno."""
    weight_sum = sum(weights.values())
    if total <= 0 or weight_sum <= 0:
        return {k: 0 for k in weights}
    exact = {k: total * w / weight_sum for k, w in weights.items()}
    out = {k: int(v) for k, v in exact.items()}
    leftover = total - sum(out.values())
    for k in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True)[:leftover]:
        out[k] += 1
    return out


def coverage(exam):
    """Qué hay en el banco del examen y dónde flojea."""
    questions = Question.query.filter_by(exam_id=exam.id, active=True).all()
    per_domain = Counter(q.domain_id for q in questions)
    per_skill = Counter((q.domain_id, q.skill) for q in questions)
    per_shape = Counter((len(q.options), len(set(q.correct))) for q in questions)

    answered = (
        db.session.query(Question.skill, func.count(Attempt.id), func.sum(db.case((Attempt.is_correct.is_(False), 1), else_=0)))
        .join(Attempt, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .group_by(Question.skill)
        .all()
    )
    weakest = sorted(
        ((skill, int(wrong or 0) / total, total) for skill, total, wrong in answered
         if skill and total >= WEAK_MIN_ATTEMPTS and wrong),
        key=lambda row: (-row[1], -row[2]),
    )[:5]

    return {
        "total": len(questions),
        "per_domain": per_domain,
        "per_skill": per_skill,
        "per_shape": per_shape,
        "weakest": weakest,
    }


def suggested_split(exam, count, cov):
    """Cuántas preguntas pedir por dominio y por formato."""
    by_domain = largest_remainder(count, {d.number: d.weight for d in exam.domains})
    shares = {(f.option_count, f.correct_count): f.target_share for f in exam.formats}
    if all(s is not None for s in shares.values()) and shares:
        # Lo que falta para que, tras añadir `count`, cada formato quede en su proporción.
        future_total = cov["total"] + count
        need = {shape: max(0.0, future_total * share - cov["per_shape"].get(shape, 0)) for shape, share in shares.items()}
        by_format = largest_remainder(count, need if sum(need.values()) else shares)
    else:
        by_format = {}
    return by_domain, by_format


def next_ids(exam):
    """Siguiente `id` libre por dominio, siguiendo la numeración d<dominio>-NN del banco."""
    highest = defaultdict(int)
    for (ext_id,) in Question.query.filter_by(exam_id=exam.id).with_entities(Question.ext_id):
        match = EXT_ID.match(ext_id)
        if match:
            number, seq = int(match.group(1)), int(match.group(2))
            highest[number] = max(highest[number], seq)
    return {d.number: f"d{d.number}-{highest[d.number] + 1:02}" for d in exam.domains}


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def _shape_text(options, correct):
    return f"{options} opciones con {_plural(correct, 'correcta', 'correctas')}"


def build_kit(exam, count=DEFAULT_COUNT):
    """El Markdown del kit para `exam`, pidiendo `count` preguntas."""
    cov = coverage(exam)
    by_domain, by_format = suggested_split(exam, count, cov)
    ids = next_ids(exam)
    used_ids = sorted(ext_id for (ext_id,) in Question.query.filter_by(exam_id=exam.id).with_entities(Question.ext_id))

    lines = [
        f"# Kit para generar preguntas · {exam.code}",
        "",
        "> Pega este bloque entero en una conversación con Claude. Lo que devuelva se importa en "
        "«Preguntas» del entrenador, que lo valida antes de insertar nada.",
        "",
        "## Encargo",
        "",
        f"Genera **{count} preguntas nuevas** de tipo test para preparar el examen **{exam.name} ({exam.code})**"
        + (f", que se presenta el {exam.exam_date.strftime('%d/%m/%Y')}" if exam.exam_date else "")
        + ". Sigue el reparto sugerido de más abajo, que apunta a donde el banco tiene huecos.",
        "",
        "## Reglas de redacción",
        "",
        "- Escribe en español de España.",
        "- Cada pregunta es un escenario breve y realista seguido de una pregunta que obliga a aplicar el "
        "conocimiento, no a recordar una definición.",
        "- En las de una correcta, una sola opción defendible. En las de varias, exactamente las que diga "
        "el formato: el examen no da crédito parcial, hay que acertarlas todas.",
        "- Distractores plausibles: errores típicos, prácticas que suenan bien pero no encajan en el "
        "escenario, opciones correctas en otro contexto. Nada de «todas las anteriores», «ninguna de las "
        "anteriores» ni opciones absurdas.",
        "- Opciones de longitud y tono parecidos: la correcta no puede delatarse por ser la más larga o la "
        "más matizada.",
        "- `w` explica por qué la correcta lo es y por qué atrae el distractor principal.",
        "- `h` es una pista opcional que orienta el razonamiento sin desvelar la respuesta.",
        "- No repitas ningún `id` de la lista del final; sigue la numeración sugerida.",
        "",
        "## El examen",
        "",
        "| Dominio | Nombre | Peso | En el banco |",
        "|---|---|---|---|",
    ]
    for d in exam.domains:
        lines.append(f"| {d.number} | {d.name} | {d.weight} % | {cov['per_domain'].get(d.id, 0)} |")

    if any(d.skills for d in exam.domains):
        lines += ["", "Habilidades de la guía oficial (entre paréntesis, preguntas que ya las cubren):", ""]
        for d in exam.domains:
            if not d.skills:
                continue
            lines.append(f"**Dominio {d.number} · {d.short_name}**")
            lines += [f"- {s.code} — {s.description} ({cov['per_skill'].get((d.id, s.code), 0)})" for s in d.skills]
            lines.append("")
    else:
        lines += ["", "Este examen no tiene habilidades dadas de alta: usa en `hab` el código de la guía "
                      "oficial si lo conoces, o el número del dominio.", ""]

    lines += ["Formatos de pregunta admitidos (la importación rechaza cualquier otro):", ""]
    lines += ["| Formato | Proporción objetivo | En el banco |", "|---|---|---|"]
    for f in exam.formats:
        have = cov["per_shape"].get((f.option_count, f.correct_count), 0)
        target = "—" if f.target_share is None else f"{round(f.target_share * 100)} %"
        lines.append(f"| {_shape_text(f.option_count, f.correct_count)} | {target} | {have} |")

    lines += ["", "## Dónde faltan preguntas", ""]
    gaps = []
    if any(d.skills for d in exam.domains):
        empty = [f"{s.code}" for d in exam.domains for s in d.skills if not cov["per_skill"].get((d.id, s.code))]
        thin = [f"{s.code}" for d in exam.domains for s in d.skills if cov["per_skill"].get((d.id, s.code)) == 1]
        if empty:
            gaps.append(f"- Habilidades sin ninguna pregunta: {', '.join(empty)}.")
        if thin:
            gaps.append(f"- Habilidades con una sola pregunta: {', '.join(thin)}.")
    if cov["weakest"]:
        weak = ", ".join(f"{skill} ({round(rate * 100)} % de fallos en {total} respuestas)" for skill, rate, total in cov["weakest"])
        gaps.append(f"- Las habilidades que más se fallan, para reforzarlas con enfoques nuevos: {weak}.")
    for f in exam.formats:
        if f.target_share is None or not cov["total"]:
            continue
        have = cov["per_shape"].get((f.option_count, f.correct_count), 0)
        share = have / cov["total"]
        if share < f.target_share - 0.02:
            gaps.append(
                f"- Formato de {_shape_text(f.option_count, f.correct_count)}: {round(share * 100)} % del banco, "
                f"por debajo del {round(f.target_share * 100)} % objetivo."
            )
    lines += gaps or ["- No hay huecos claros: reparte según los pesos y varía los escenarios."]

    lines += ["", f"## Reparto sugerido para estas {count}", ""]
    for d in exam.domains:
        lines.append(f"- Dominio {d.number} ({d.short_name}): {_plural(by_domain.get(d.number, 0), 'pregunta', 'preguntas')}.")
    if by_format:
        lines.append("- Por formato: " + "; ".join(
            f"{_shape_text(o, c)}: {n}" for (o, c), n in by_format.items() if n) + ".")

    example_format = exam.formats[0] if exam.formats else None
    first_domain = exam.domains[0] if exam.domains else None
    example = {
        "id": ids.get(first_domain.number) if first_domain else "d1-01",
        "dom": first_domain.number if first_domain else 1,
        "hab": (first_domain.skills[0].code if first_domain and first_domain.skills else "1.1.1"),
        "t": "m" if example_format and example_format.correct_count > 1 else "s",
        "q": "Escenario breve y realista. ¿Qué debería hacer…?",
        "o": [f"Opción {chr(65 + i)}" for i in range(example_format.option_count if example_format else 4)],
        "ok": list(range(example_format.correct_count if example_format else 1)),
        "w": "Por qué la correcta lo es y por qué atrae el distractor principal.",
        "h": "Pista que orienta sin desvelar la respuesta.",
    }
    lines += [
        "",
        "## Formato de salida",
        "",
        "Devuelve **solo** este bloque JSON, sin texto antes ni después:",
        "",
        "```json",
        json.dumps({"exam": exam.code, "questions": [example]}, ensure_ascii=False, indent=2),
        "```",
        "",
        "| Clave | Contenido |",
        "|---|---|",
        "| `id` | Único dentro del examen, con el formato `d<dominio>-NN` |",
        "| `dom` | Número de dominio de la tabla de arriba |",
        "| `hab` | Código de la habilidad |",
        "| `t` | `s` si hay una correcta, `m` si hay varias |",
        "| `q` | Escenario y pregunta |",
        "| `o` | Opciones, tantas como diga el formato |",
        "| `ok` | Índices de las correctas, empezando en 0 |",
        "| `w` | Explicación |",
        "| `h` | Pista (opcional) |",
        "",
        "Siguientes `id` libres por dominio: " + ", ".join(ids[d.number] for d in exam.domains) + ".",
        "",
        "## `id` ya usados",
        "",
        ", ".join(used_ids) if used_ids else "Ninguno: el banco de este examen está vacío.",
        "",
    ]
    return "\n".join(lines)
