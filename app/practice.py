"""Vistas de página: inicio, sesión de práctica, historial."""
from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.exams import current_exam
from app.extensions import db
from app.models import Domain, Question, StudySession
from app.progress import reset_progress
from app.sampling import domain_readiness
from app.srs import review_summary

# Abreviaturas de los días para la previsión de la portada. strftime
# depende del locale del servidor, que en Render es inglés.
WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")

bp = Blueprint("practice", __name__)


@bp.route("/")
@login_required
def home():
    exam = current_exam()
    domains = exam.domains
    readiness = {d.number: domain_readiness(exam, d.number) for d in domains}
    counts_by_number = dict(
        db.session.query(Domain.number, func.count(Question.id))
        .join(Question, Question.domain_id == Domain.id)
        .filter(Domain.exam_id == exam.id, Question.active.is_(True))
        .group_by(Domain.number)
        .all()
    )
    question_counts = {d.number: counts_by_number.get(d.number, 0) for d in domains}
    total_questions = sum(question_counts.values())
    history = (
        StudySession.query.filter(StudySession.exam_id == exam.id, StudySession.finished_at.isnot(None))
        .order_by(StudySession.finished_at.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "home.html",
        exam=exam,
        domains=domains,
        readiness=readiness,
        question_counts=question_counts,
        total_questions=total_questions,
        review=review_summary(exam),
        weekdays=WEEKDAYS,
        history=history,
        pass_threshold=exam.pass_threshold_pct,
        recall_first=current_user.recall_first,
    )


@bp.route("/preferencias/primero-piensa", methods=["POST"])
@login_required
def toggle_recall_first():
    """Enciende o apaga el modo «primero piensa». Se aplica desde la siguiente tanda."""
    current_user.recall_first = not current_user.recall_first
    db.session.commit()
    return redirect(url_for("practice.home"))


@bp.route("/tanda")
@login_required
def session_view():
    exam = current_exam()
    return render_template(
        "session.html",
        pass_threshold=exam.pass_threshold_pct,
        domain_short={d.number: d.short_name for d in exam.domains},
    )


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
