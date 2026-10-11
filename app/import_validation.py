"""Validador del formato de importación de preguntas.

Único punto de verdad, usado por la vista web (app/questions_admin.py) y
por el comando de consola (app/cli.py). Formato documentado en
reference/formato-preguntas.md.
"""
from dataclasses import dataclass, field

from app.exams import current_exam
from app.extensions import db
from app.models import Exam, Question

REQUIRED_KEYS = {"id", "dom", "q", "o", "ok", "w"}


@dataclass
class ValidationResult:
    accepted: list = field(default_factory=list)  # dicts normalizados, listos para insertar
    rejected: list = field(default_factory=list)  # (ext_id_o_indice, motivo)


def _reject(rejected, identifier, reason):
    rejected.append((identifier, reason))


class ImportPayloadError(ValueError):
    """El bloque pegado no tiene una forma que se pueda importar."""


def resolve_payload(data):
    """(examen, lista de preguntas) a partir de lo que se pegó o se leyó del fichero.

    Admite dos formas (reference/formato-preguntas.md):
    - El array de preguntas tal cual: entran en el examen en curso.
    - {"exam": "<código>", "questions": [...]}: entran en ese examen, que
      es lo que produce el kit de generación (#20).
    """
    if isinstance(data, list):
        return current_exam(), data
    if isinstance(data, dict) and "questions" in data:
        code = data.get("exam")
        if not isinstance(code, str) or not code.strip():
            raise ImportPayloadError(
                "El bloque trae «questions» pero no dice a qué examen van: añade "
                "\"exam\": \"<código>\" o pega solo el array de preguntas."
            )
        exam = Exam.query.filter(db.func.lower(Exam.code) == code.strip().lower()).first()
        if exam is None:
            raise ImportPayloadError(
                f"No hay ningún examen con el código {code}. Créalo en «Exámenes» "
                "o corrige el campo «exam» del bloque."
            )
        if not isinstance(data["questions"], list):
            raise ImportPayloadError("El campo «questions» tiene que ser una lista de preguntas.")
        return exam, data["questions"]
    raise ImportPayloadError(
        "No se reconoce el formato: pega un array de preguntas o un objeto "
        "{\"exam\": \"<código>\", \"questions\": [...]}."
    )


def validate_import(raw_items, exam=None, existing_ext_ids=None):
    """Valida una lista de preguntas en formato corto (id/dom/hab/t/q/o/ok/w/h).

    Las preguntas entran en `exam` (por defecto, el examen en curso: ver
    app/exams.py), y su `dom` se resuelve contra los dominios de ese
    examen. `existing_ext_ids` permite comprobar duplicados sin golpear la
    base por cada pregunta del bloque; si no se pasa, se consultan una vez
    los del examen. Devuelve un ValidationResult con las preguntas aceptadas
    normalizadas al formato largo del modelo Question y los motivos de
    descarte de las demás.
    """
    exam = exam or current_exam()
    domain_id_by_number = {d.number: d.id for d in exam.domains}
    allowed_shapes = {(f.option_count, f.correct_count) for f in exam.formats}
    allowed_text = ", ".join(
        f"{o} opciones con {c} {'correcta' if c == 1 else 'correctas'}" for o, c in sorted(allowed_shapes)
    )
    if existing_ext_ids is None:
        existing_ext_ids = {
            ext_id for (ext_id,) in Question.query.filter_by(exam_id=exam.id).with_entities(Question.ext_id)
        }

    result = ValidationResult()
    seen_in_block = set()

    if not isinstance(raw_items, list):
        raw_items = [raw_items]

    for index, item in enumerate(raw_items):
        label = f"posición {index + 1}"

        if not isinstance(item, dict):
            _reject(result.rejected, label, "no es un objeto JSON válido")
            continue

        missing = REQUIRED_KEYS - item.keys()
        if missing:
            ext_id = item.get("id", label)
            _reject(result.rejected, ext_id, f"faltan las claves: {', '.join(sorted(missing))}")
            continue

        ext_id = item["id"]
        label = f'"{ext_id}"'

        if not isinstance(ext_id, str) or not ext_id.strip():
            _reject(result.rejected, label, "campo 'id' vacío o no es texto")
            continue

        if ext_id in existing_ext_ids:
            _reject(result.rejected, label, "ya existe en el banco (ext_id duplicado)")
            continue
        if ext_id in seen_in_block:
            _reject(result.rejected, label, "duplicado dentro de este mismo bloque")
            continue

        domain = item.get("dom")
        if isinstance(domain, bool) or domain not in domain_id_by_number:
            numbers = ", ".join(str(n) for n in sorted(domain_id_by_number))
            _reject(
                result.rejected,
                label,
                f"campo 'dom' no es un dominio de {exam.code} (admite {numbers}): {domain!r}",
            )
            continue

        question_type = item.get("t")
        if question_type not in (None, "s", "m"):
            _reject(result.rejected, label, f"campo 't' inválido (debe ser 's' o 'm'): {question_type!r}")
            continue

        options = item.get("o")
        if not isinstance(options, list) or len(options) < 2:
            _reject(result.rejected, label, "campo 'o' debe ser una lista de al menos 2 opciones")
            continue

        correct = item.get("ok")
        if not isinstance(correct, list) or not correct:
            _reject(result.rejected, label, "campo 'ok' debe ser una lista no vacía de índices")
            continue

        out_of_range = [i for i in correct if not isinstance(i, int) or not (0 <= i < len(options))]
        if out_of_range:
            _reject(
                result.rejected,
                label,
                f"campo 'ok' contiene índices fuera de rango de 'o' (0-{len(options) - 1}): {out_of_range}",
            )
            continue

        # El formato (cuántas opciones, cuántas correctas) lo dicta el examen.
        shape = (len(options), len(set(correct)))
        if shape not in allowed_shapes:
            _reject(
                result.rejected,
                label,
                f"{shape[0]} opciones con {shape[1]} {'correcta' if shape[1] == 1 else 'correctas'} "
                f"no es un formato de {exam.code} (admite {allowed_text})",
            )
            continue
        # 't' es opcional y redundante: si viene, tiene que cuadrar con 'ok'.
        derived_type = "m" if shape[1] > 1 else "s"
        if question_type is not None and question_type != derived_type:
            _reject(
                result.rejected,
                label,
                f"campo 't' dice {question_type!r} pero 'ok' tiene {shape[1]} "
                f"{'correcta' if shape[1] == 1 else 'correctas'}: "
                f"'s' es para una sola correcta y 'm' para varias",
            )
            continue
        question_type = derived_type

        stem = item.get("q")
        if not isinstance(stem, str) or not stem.strip():
            _reject(result.rejected, label, "campo 'q' (enunciado) vacío o no es texto")
            continue

        explanation = item.get("w")
        if not isinstance(explanation, str) or not explanation.strip():
            _reject(result.rejected, label, "campo 'w' (explicación) vacío o no es texto")
            continue

        seen_in_block.add(ext_id)
        result.accepted.append(
            {
                "exam_id": exam.id,
                "domain_id": domain_id_by_number[domain],
                "ext_id": ext_id,
                "skill": item.get("hab", ""),
                "type": question_type,
                "stem": stem,
                "options": options,
                "correct": sorted(set(correct)),
                "explanation": explanation,
                "hint": item.get("h"),
                "source": "import",
            }
        )

    return result


def question_to_short_format(question: Question) -> dict:
    """Formato corto de exportación (id/dom/hab/t/q/o/ok/w/h), espejo de import."""
    item = {
        "id": question.ext_id,
        "dom": question.domain.number,
        "hab": question.skill,
        "t": question.type,
        "q": question.stem,
        "o": question.options,
        "ok": question.correct,
        "w": question.explanation,
    }
    if question.hint:
        item["h"] = question.hint
    return item
