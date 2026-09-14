"""Validador del formato de importación de preguntas.

Único punto de verdad, usado por la vista web (app/questions_admin.py) y
por el comando de consola (app/cli.py). Formato documentado en
reference/formato-preguntas.md.
"""
from dataclasses import dataclass, field

from app.models import Question

REQUIRED_KEYS = {"id", "dom", "q", "o", "ok", "w"}


@dataclass
class ValidationResult:
    accepted: list = field(default_factory=list)  # dicts normalizados, listos para insertar
    rejected: list = field(default_factory=list)  # (ext_id_o_indice, motivo)


def _reject(rejected, identifier, reason):
    rejected.append((identifier, reason))


def validate_import(raw_items, existing_ext_ids=None):
    """Valida una lista de preguntas en formato corto (id/dom/hab/t/q/o/ok/w/h).

    `existing_ext_ids` permite comprobar duplicados contra la base de datos
    sin golpearla por cada pregunta del bloque (se consulta una vez fuera).
    Devuelve un ValidationResult con las preguntas aceptadas normalizadas al
    formato largo del modelo Question y los motivos de descarte de las demás.
    """
    if existing_ext_ids is None:
        existing_ext_ids = {q.ext_id for q in Question.query.with_entities(Question.ext_id).all()}

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
        if not isinstance(domain, int) or not (1 <= domain <= 4):
            _reject(result.rejected, label, f"campo 'dom' fuera de rango (1-4): {domain!r}")
            continue

        question_type = item.get("t", "s")
        if question_type not in ("s", "m"):
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

        if question_type == "m" and len(set(correct)) != 2:
            _reject(
                result.rejected,
                label,
                f"las preguntas de tipo 'm' (múltiple) exigen exactamente 2 índices correctos, hay {len(set(correct))}",
            )
            continue
        if question_type == "s" and len(set(correct)) != 1:
            _reject(
                result.rejected,
                label,
                f"las preguntas de tipo 's' (única) exigen exactamente 1 índice correcto, hay {len(set(correct))}",
            )
            continue

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
                "ext_id": ext_id,
                "domain": domain,
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
        "dom": question.domain,
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
