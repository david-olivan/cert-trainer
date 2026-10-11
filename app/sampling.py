"""Muestreo de preguntas con la ponderación oficial de cada examen.

Los dominios y sus pesos viven en la base de datos (tablas `exams` y
`domains`), que es el único punto de verdad: aquí no se escribe ninguno.
"""
import random

from sqlalchemy import func

from app.extensions import db
from app.models import Attempt, Domain, Question

FALLOS_MAX = 20


def _active_questions_by_domain(exam):
    number_by_domain_id = {d.id: d.number for d in exam.domains}
    by_domain = {number: [] for number in number_by_domain_id.values()}
    for q in Question.query.filter_by(active=True, exam_id=exam.id).all():
        by_domain[number_by_domain_id[q.domain_id]].append(q)
    return by_domain


def weighted_sample(exam, n, pool_by_domain=None):
    """Muestrea `n` preguntas respetando el peso oficial de cada dominio del examen."""
    by_domain = pool_by_domain or _active_questions_by_domain(exam)
    out = []
    for domain, weight in ((d.number, d.weight) for d in exam.domains):
        pool = by_domain.get(domain, [])[:]
        random.shuffle(pool)
        k = min(len(pool), round(n * weight / 100))
        out.extend(pool[:k])

    if len(out) < n:
        chosen_ids = {q.id for q in out}
        rest = [q for domain in by_domain.values() for q in domain if q.id not in chosen_ids]
        random.shuffle(rest)
        out.extend(rest[: n - len(out)])

    random.shuffle(out)
    return out[:n]


def build_queue(exam, mode, domain=None):
    """Construye la cola de preguntas de `exam` para un modo de práctica.

    Puerto directo de build()/weighted() del prototipo
    (reference/entrenador-artefacto.html).
    """
    if mode == "dominio":
        numbers = [d.number for d in exam.domains]
        if domain not in numbers:
            raise ValueError(
                f"{exam.code} no tiene el dominio {domain!r}: elige uno de "
                f"{', '.join(str(n) for n in numbers)}."
            )
        pool = (
            Question.query.join(Domain, Question.domain_id == Domain.id)
            .filter(Question.active.is_(True), Question.exam_id == exam.id, Domain.number == domain)
            .all()
        )
        random.shuffle(pool)
        return pool

    if mode == "fallos":
        counts = (
            Attempt.query.join(Question)
            .filter(Attempt.is_correct.is_(False), Question.active.is_(True), Question.exam_id == exam.id)
            .with_entities(Attempt.question_id, func.count(Attempt.id).label("fails"))
            .group_by(Attempt.question_id)
            .order_by(func.count(Attempt.id).desc())
            .limit(FALLOS_MAX)
            .all()
        )
        ids_in_order = [qid for qid, _fails in counts]
        questions_by_id = {q.id: q for q in Question.query.filter(Question.id.in_(ids_in_order)).all()}
        return [questions_by_id[qid] for qid in ids_in_order if qid in questions_by_id]

    if mode == "rapida":
        return weighted_sample(exam, 10)

    if mode == "simulacro":
        total_active = Question.query.filter_by(active=True, exam_id=exam.id).count()
        return weighted_sample(exam, total_active)

    raise ValueError(f"Modo de práctica desconocido: {mode!r}")


def domain_readiness(exam, domain):
    """Porcentaje de aciertos acumulado en un dominio, o None si no hay intentos."""
    rows = (
        db.session.query(Attempt.is_correct)
        .join(Question, Attempt.question_id == Question.id)
        .join(Domain, Question.domain_id == Domain.id)
        .filter(Question.exam_id == exam.id, Domain.number == domain)
        .all()
    )
    if not rows:
        return None
    total = len(rows)
    correct = sum(1 for (is_correct,) in rows if is_correct)
    return round(correct / total * 100)
