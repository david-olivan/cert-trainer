"""API JSON de la tanda en curso.

El estado de la cola (qué preguntas, en qué orden, con qué reordenamiento
de opciones) vive en la sesión de Flask del lado servidor, nunca en el
cliente: así el JS no puede leer la respuesta correcta inspeccionando la
red o el propio código. Cada respuesta se guarda en Attempt al vuelo
(SPEC.md 1.3), no al terminar la tanda.
"""
import random

from flask import Blueprint, jsonify, request, session
from flask_login import login_required

from app.extensions import db
from app.models import Attempt, Question, StudySession
from app.sampling import DOMAIN_SHORT, build_queue

bp = Blueprint("api", __name__, url_prefix="/api/session")

SESSION_KEY = "practice_queue"


def _public_question(question, option_order):
    """Pregunta sin el campo `correct`, con las opciones en el orden barajado."""
    shuffled_options = [question.options[i] for i in option_order]
    return {
        "ext_id": question.ext_id,
        "domain": question.domain,
        "domain_short": DOMAIN_SHORT[question.domain],
        "skill": question.skill,
        "type": question.type,
        "stem": question.stem,
        "options": shuffled_options,
        "hint": question.hint,
    }


def _current_state():
    state = session.get(SESSION_KEY)
    if not state:
        return None
    return state


@bp.route("/start", methods=["POST"])
@login_required
def start():
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode")
    domain = payload.get("domain")

    if mode not in ("simulacro", "rapida", "dominio", "fallos"):
        return jsonify(error="Modo de práctica desconocido."), 400
    if mode == "dominio" and domain not in (1, 2, 3, 4):
        return jsonify(error="Indica un dominio entre 1 y 4."), 400

    try:
        questions = build_queue(mode, domain=domain if mode == "dominio" else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not questions:
        return jsonify(error="No hay preguntas disponibles para este modo todavía."), 409

    study_session = StudySession(mode=mode, domain=domain if mode == "dominio" else None, question_count=len(questions))
    db.session.add(study_session)
    db.session.commit()

    # Reordenamiento de opciones por pregunta (SPEC.md 1.3: aleatorizar en
    # cada presentación). Se guarda el orden, no las respuestas, en la
    # sesión de servidor.
    option_orders = {}
    for q in questions:
        order = list(range(len(q.options)))
        random.shuffle(order)
        option_orders[q.ext_id] = order

    session[SESSION_KEY] = {
        "study_session_id": study_session.id,
        "mode": mode,
        "domain": domain,
        "queue": [q.ext_id for q in questions],
        "option_orders": option_orders,
        "index": 0,
        "results": [],  # True/False por pregunta respondida
    }

    first_question = questions[0]
    return jsonify(
        study_session_id=study_session.id,
        total=len(questions),
        index=0,
        minutes_per_question=2,
        question=_public_question(first_question, option_orders[first_question.ext_id]),
    )


@bp.route("/answer", methods=["POST"])
@login_required
def answer():
    state = _current_state()
    if not state or state["index"] >= len(state["queue"]):
        return jsonify(error="No hay ninguna tanda en curso."), 409

    payload = request.get_json(silent=True) or {}
    selected = payload.get("selected")
    seconds_spent = payload.get("seconds_spent")
    if not isinstance(selected, list):
        return jsonify(error="Falta 'selected' (lista de índices elegidos)."), 400

    ext_id = state["queue"][state["index"]]
    question = Question.query.filter_by(ext_id=ext_id).first()
    if question is None:
        return jsonify(error="La pregunta ya no existe en el banco."), 409

    order = state["option_orders"][ext_id]
    # `selected` llega en índices del orden barajado; se traduce al índice
    # original para comparar contra Question.correct.
    selected_original = sorted(order[i] for i in selected if 0 <= i < len(order))
    correct_original = sorted(question.correct)
    is_correct = selected_original == correct_original and bool(selected_original)

    attempt = Attempt(
        question_id=question.id,
        session_id=state["study_session_id"],
        selected=selected_original,
        is_correct=is_correct,
        seconds_spent=seconds_spent if isinstance(seconds_spent, int) else None,
    )
    db.session.add(attempt)
    db.session.commit()

    state["results"].append(is_correct)
    state["index"] += 1
    session[SESSION_KEY] = state

    correct_in_shown_order = sorted(order.index(i) for i in question.correct)

    return jsonify(
        is_correct=is_correct,
        correct_options=correct_in_shown_order,
        explanation=question.explanation,
        skill=question.skill,
        index=state["index"],
        total=len(state["queue"]),
    )


@bp.route("/next", methods=["GET"])
@login_required
def next_question():
    state = _current_state()
    if not state:
        return jsonify(error="No hay ninguna tanda en curso."), 409
    if state["index"] >= len(state["queue"]):
        return jsonify(done=True)

    ext_id = state["queue"][state["index"]]
    question = Question.query.filter_by(ext_id=ext_id).first()
    if question is None:
        return jsonify(error="La pregunta ya no existe en el banco."), 409

    return jsonify(
        done=False,
        index=state["index"],
        total=len(state["queue"]),
        question=_public_question(question, state["option_orders"][ext_id]),
    )


@bp.route("/finish", methods=["POST"])
@login_required
def finish():
    state = _current_state()
    if not state:
        return jsonify(error="No hay ninguna tanda en curso."), 409

    study_session = StudySession.query.get(state["study_session_id"])
    if study_session is None:
        return jsonify(error="La sesión de estudio ya no existe."), 409

    results = state["results"]
    answered = len(results)
    correct = sum(1 for r in results if r)
    pct = round(correct / answered * 100) if answered else 0

    per_domain = {}
    for ext_id, result in zip(state["queue"][:answered], results):
        question = Question.query.filter_by(ext_id=ext_id).first()
        if question is None:
            continue
        bucket = per_domain.setdefault(question.domain, {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += 1 if result else 0

    per_domain_pct = {
        str(domain): round(v["correct"] / v["total"] * 100) for domain, v in per_domain.items() if v["total"]
    }

    from datetime import datetime, timezone

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
