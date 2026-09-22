"""Vistas de página: inicio, sesión de práctica, historial."""
from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required
from sqlalchemy import distinct, func

from app.extensions import db
from app.models import Attempt, Question, StudySession
from app.progress import reset_progress
from app.sampling import (
    DOMAIN_NAMES,
    DOMAIN_SHORT,
    DOMAIN_WEIGHTS,
    PASS_THRESHOLD_PCT,
    domain_readiness,
)

bp = Blueprint("practice", __name__)


@bp.route("/")
@login_required
def home():
    readiness = {d: domain_readiness(d) for d in DOMAIN_WEIGHTS}
    question_counts = {
        d: Question.query.filter_by(active=True, domain=d).count() for d in DOMAIN_WEIGHTS
    }
    total_questions = sum(question_counts.values())
    # Cuenta preguntas distintas falladas contando identificadores, no filas
    # enteras. Un SELECT DISTINCT sobre la entidad Question arrastra las
    # columnas `options` y `correct`, que son json, y Postgres no sabe
    # comparar ese tipo por igualdad: la portada devolvía 500 en
    # producción mientras en sqlite pasaba sin queja.
    # Se filtra por active, como hace build_queue("fallos"), para que el
    # número de la portada sea el de las preguntas que el modo va a servir.
    failed_count = (
        db.session.query(func.count(distinct(Attempt.question_id)))
        .select_from(Attempt)
        .join(Question, Attempt.question_id == Question.id)
        .filter(Attempt.is_correct.is_(False), Question.active.is_(True))
        .scalar()
    )
    history = (
        StudySession.query.filter(StudySession.finished_at.isnot(None))
        .order_by(StudySession.finished_at.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "home.html",
        readiness=readiness,
        domain_names=DOMAIN_NAMES,
        domain_short=DOMAIN_SHORT,
        domain_weights=DOMAIN_WEIGHTS,
        question_counts=question_counts,
        total_questions=total_questions,
        failed_count=failed_count,
        history=history,
        pass_threshold=PASS_THRESHOLD_PCT,
    )


@bp.route("/tanda")
@login_required
def session_view():
    return render_template("session.html", pass_threshold=PASS_THRESHOLD_PCT)


@bp.route("/reiniciar-progreso", methods=["POST"])
@login_required
def reset_progress_view():
    """Borra sesiones e intentos. El banco de preguntas no se toca."""
    removed = reset_progress()
    if removed["attempts"] or removed["sessions"]:
        flash(
            f"Progreso borrado: {removed['sessions']} sesiones y "
            f"{removed['attempts']} respuestas. Las preguntas del banco siguen intactas.",
            "ok",
        )
    else:
        flash("No había ningún progreso que borrar.", "ok")
    return redirect(url_for("practice.home"))
