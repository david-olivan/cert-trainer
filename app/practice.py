"""Vistas de página: inicio, sesión de práctica, historial."""
from flask import Blueprint, abort, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.exams import SESSION_EXAM_KEY, NoExamError, active_exam, current_exam, session_exam
from app.extensions import db
from app.models import Domain, Exam, Question, StudySession
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
        exams=Exam.query.filter_by(archived=False).order_by(Exam.code).all(),
        active=active_exam(),
        studying_other=session_exam() is not None,
        history=history,
        pass_threshold=exam.pass_threshold_pct,
        recall_first=current_user.recall_first,
    )


@bp.app_context_processor
def inject_chrome_exam():
    """Código del examen en curso para la barra superior de todas las páginas."""
    if not current_user.is_authenticated:
        return {}
    try:
        return {"chrome_exam_code": current_exam().code}
    except NoExamError:
        return {}


def _open_exam(exam_id):
    exam = db.session.get(Exam, exam_id)
    if exam is None:
        abort(404)
    if exam.archived:
        flash(f"{exam.code} está archivado. Desarchívalo en «Exámenes» para estudiarlo.")
        return None
    return exam


@bp.route("/examen/<int:exam_id>/estudiar", methods=["POST"])
@login_required
def study_exam(exam_id):
    """Estudiar otro examen solo en este navegador, sin cambiar el activo."""
    exam = _open_exam(exam_id)
    if exam is not None:
        # Sin flash: la portada ya lo dice con el aviso fijo de «estudiando
        # de forma puntual» mientras dure.
        session[SESSION_EXAM_KEY] = exam.id
    return redirect(url_for("practice.home"))


@bp.route("/examen/<int:exam_id>/activar", methods=["POST"])
@login_required
def activate_exam(exam_id):
    """Fijar el examen activo: el que se abre al entrar, en cualquier dispositivo."""
    exam = _open_exam(exam_id)
    if exam is not None:
        current_user.active_exam_id = exam.id
        db.session.commit()
        session.pop(SESSION_EXAM_KEY, None)
        flash(f"{exam.code} es tu examen activo.")
    return redirect(url_for("practice.home"))


@bp.route("/examen/volver-al-activo", methods=["POST"])
@login_required
def back_to_active():
    session.pop(SESSION_EXAM_KEY, None)
    return redirect(url_for("practice.home"))


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
