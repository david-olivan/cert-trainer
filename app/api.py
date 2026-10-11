"""API JSON de la tanda en curso.

El estado de la cola (qué preguntas, en qué orden, con qué reordenamiento
de opciones y por dónde va) vive en StudySession, en la base de datos, y
la cookie de sesión solo lleva su id (#18). Nunca viaja al cliente: así el
JS no puede leer la respuesta correcta inspeccionando la red o el propio
código. Cada respuesta se guarda en Attempt al vuelo (SPEC.md 1.3), no al
terminar la tanda.
"""
import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session
from flask_login import current_user, login_required

from app.exams import current_exam
from app.extensions import db
from app.models import Attempt, Question, StudySession
from app.sampling import build_queue
from app.srs import review

bp = Blueprint("api", __name__, url_prefix="/api/session")

SESSION_KEY = "practice_queue"
# Versión de lo que guarda la cookie. Desde la 3 es solo el id de la
# StudySession; una tanda empezada con una versión anterior (la cola entera
# en la cookie) no se puede continuar y se descarta.
QUEUE_VERSION = 3

CONFIDENCE_VALUES = ("sure", "unsure")


def _public_question(question, option_order):
    """Pregunta sin el campo `correct`, con las opciones en el orden barajado."""
    shuffled_options = [question.options[i] for i in option_order]
    return {
        "ext_id": question.ext_id,
        "domain": question.domain.number,
        "domain_short": question.domain.short_name,
        "skill": question.skill,
        "type": question.type,
        "stem": question.stem,
        "options": shuffled_options,
        "hint": question.hint,
    }


def _current_session():
    """La StudySession en curso de este navegador, o None."""
    state = session.get(SESSION_KEY)
    if not state:
        return None
    if state.get("version") != QUEUE_VERSION:
        session.pop(SESSION_KEY, None)
        return None
    study_session = db.session.get(StudySession, state["study_session_id"])
    if study_session is None or study_session.finished_at is not None or study_session.queue is None:
        session.pop(SESSION_KEY, None)
        return None
    return study_session


@bp.route("/start", methods=["POST"])
@login_required
def start():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    domain = payload.get("domain")

    if mode not in ("simulacro", "rapida", "dominio", "repaso"):
        return jsonify(error="Modo de práctica desconocido."), 400
    exam = current_exam()
    if mode == "dominio" and domain is None:
        return jsonify(error="Falta indicar el dominio. Vuelve al inicio y elige uno."), 400

    try:
        questions = build_queue(exam, mode, domain=domain if mode == "dominio" else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not questions:
        if mode == "repaso":
            return jsonify(error="No tienes nada pendiente hoy. Vuelve al inicio y haz una tanda rápida."), 409
        return jsonify(error="No hay preguntas disponibles para este modo todavía."), 409

    # Reordenamiento de opciones por pregunta (SPEC.md 1.3: aleatorizar en
    # cada presentación). Se guarda el orden, no las respuestas.
    option_orders = {}
    for q in questions:
        order = list(range(len(q.options)))
        random.shuffle(order)
        option_orders[str(q.id)] = order  # claves de texto: la columna es JSON

    # «Primero piensa» (issue #14) lo decide el servidor al empezar, no el
    # cliente: es la preferencia guardada, salvo en simulacro, porque el
    # examen real no funciona así.
    recall_first = bool(current_user.recall_first) and mode != "simulacro"

    study_session = StudySession(
        exam_id=exam.id,
        mode=mode,
        domain=domain if mode == "dominio" else None,
        question_count=len(questions),
        queue=[q.id for q in questions],
        option_orders=option_orders,
        position=0,
        recall_first=recall_first,
    )
    db.session.add(study_session)
    db.session.commit()

    session[SESSION_KEY] = {"version": QUEUE_VERSION, "study_session_id": study_session.id}

    first_question = questions[0]
    return jsonify(
        study_session_id=study_session.id,
        total=len(questions),
        index=0,
        minutes_per_question=exam.minutes_per_question,
        recall_first=recall_first,
        question=_public_question(first_question, option_orders[str(first_question.id)]),
    )


@bp.route("/answer", methods=["POST"])
@login_required
def answer():
    study_session = _current_session()
    if study_session is None or study_session.position >= len(study_session.queue):
        return jsonify(error="No hay ninguna tanda en curso."), 409

    payload = request.get_json(silent=True) or {}
    selected = payload.get("selected")
    seconds_spent = payload.get("seconds_spent")
    if not isinstance(selected, list):
        return jsonify(error="Falta 'selected' (lista de índices elegidos)."), 400

    # Las señales son opcionales para no romper una pestaña abierta con el
    # JavaScript anterior: si no llegan se guardan como desconocidas (nulo),
    # nunca con un valor supuesto. Si llegan mal, sí es un error.
    confidence = payload.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE_VALUES:
        return jsonify(error="'confidence' debe ser \"sure\" o \"unsure\"."), 400
    hint_used = payload.get("hint_used")
    if hint_used is not None and not isinstance(hint_used, bool):
        return jsonify(error="'hint_used' debe ser true o false."), 400

    recall_first = bool(study_session.recall_first)
    seconds_to_reveal = payload.get("seconds_to_reveal")
    if seconds_to_reveal is not None and (
        isinstance(seconds_to_reveal, bool) or not isinstance(seconds_to_reveal, int) or seconds_to_reveal < 0
    ):
        return jsonify(error="'seconds_to_reveal' debe ser un número entero de segundos, 0 o más."), 400
    if not recall_first:
        seconds_to_reveal = None

    question_id = study_session.queue[study_session.position]
    question = db.session.get(Question, question_id)
    if question is None:
        return jsonify(error="La pregunta ya no existe en el banco."), 409

    order = study_session.option_orders[str(question_id)]
    # `selected` llega en índices del orden barajado; se traduce al índice
    # original para comparar contra Question.correct.
    selected_original = sorted(order[i] for i in selected if 0 <= i < len(order))
    correct_original = sorted(question.correct)
    is_correct = selected_original == correct_original and bool(selected_original)

    now = datetime.now(timezone.utc)
    attempt = Attempt(
        answered_at=now,
        question_id=question.id,
        session_id=study_session.id,
        selected=selected_original,
        is_correct=is_correct,
        seconds_spent=seconds_spent if isinstance(seconds_spent, int) else None,
        confidence=confidence,
        hint_used=hint_used,
        option_order=list(order),
        recall_first=recall_first,
        seconds_to_reveal=seconds_to_reveal,
    )
    # La respuesta es también una revisión FSRS (#16): el estado de la
    # pregunta se actualiza en la misma transacción que guarda el intento,
    # para que nunca quede uno sin el otro.
    review(attempt, question, question.exam, now=now)
    db.session.add(attempt)
    # Avanzar la cola entra en la misma transacción que la respuesta: si se
    # corta a mitad, ni se pierde la respuesta ni se salta la pregunta.
    study_session.position += 1
    db.session.commit()

    correct_in_shown_order = sorted(order.index(i) for i in question.correct)

    return jsonify(
        is_correct=is_correct,
        correct_options=correct_in_shown_order,
        explanation=question.explanation,
        skill=question.skill,
        index=study_session.position,
        total=len(study_session.queue),
    )


@bp.route("/next", methods=["GET"])
@login_required
def next_question():
    study_session = _current_session()
    if study_session is None:
        return jsonify(error="No hay ninguna tanda en curso."), 409
    if study_session.position >= len(study_session.queue):
        return jsonify(done=True)

    question_id = study_session.queue[study_session.position]
    question = db.session.get(Question, question_id)
    if question is None:
        return jsonify(error="La pregunta ya no existe en el banco."), 409

    return jsonify(
        done=False,
        index=study_session.position,
        total=len(study_session.queue),
        question=_public_question(question, study_session.option_orders[str(question_id)]),
    )


@bp.route("/finish", methods=["POST"])
@login_required
def finish():
    study_session = _current_session()
    if study_session is None:
        return jsonify(error="No hay ninguna tanda en curso."), 409

    # El resultado sale de las respuestas guardadas, que son la verdad: la
    # cola solo dice qué faltaba por servir.
    attempts = Attempt.query.filter_by(session_id=study_session.id).all()
    answered = len(attempts)
    correct = sum(1 for a in attempts if a.is_correct)
    pct = round(correct / answered * 100) if answered else 0

    per_domain = {}
    for attempt in attempts:
        bucket = per_domain.setdefault(attempt.question.domain.number, {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += 1 if attempt.is_correct else 0

    per_domain_pct = {
        str(domain): round(v["correct"] / v["total"] * 100) for domain, v in per_domain.items() if v["total"]
    }

    study_session.finished_at = datetime.now(timezone.utc)
    study_session.score_pct = pct
    study_session.question_count = answered
    db.session.commit()

    session.pop(SESSION_KEY, None)

    return jsonify(
        score_pct=pct,
        answered=answered,
        correct=correct,
        per_domain_pct=per_domain_pct,
    )
