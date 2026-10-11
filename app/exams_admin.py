"""Gestión de exámenes (issue #19): lista, alta, edición, archivado y borrado.

La lógica del formulario está en app/exam_form.py; aquí solo las rutas.
"""
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import func

from app import exam_form, kit
from app.exams import active_exam, current_exam
from app.extensions import db
from app.models import Exam, Question, StudySession, User

bp = Blueprint("exams_admin", __name__, url_prefix="/examenes")


def _get_exam(exam_id):
    exam = db.session.get(Exam, exam_id)
    if exam is None:
        abort(404)
    return exam


@bp.route("/")
@login_required
def index():
    exams = Exam.query.order_by(Exam.archived, Exam.code).all()
    question_counts = dict(
        db.session.query(Question.exam_id, func.count(Question.id)).group_by(Question.exam_id).all()
    )
    session_counts = dict(
        db.session.query(StudySession.exam_id, func.count(StudySession.id)).group_by(StudySession.exam_id).all()
    )
    return render_template(
        "exams.html",
        exams=exams,
        current=current_exam(),
        active=active_exam(),
        question_counts=question_counts,
        session_counts=session_counts,
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "GET":
        return render_template("exam_form.html", form=exam_form.empty_form(), exam=None)
    form = exam_form.parse_form(request.form)
    if not exam_form.validate(form):
        return render_template("exam_form.html", form=form, exam=None), 400
    exam = exam_form.apply(form, Exam())
    flash(f"Examen {exam.code} creado.")
    return redirect(url_for("exams_admin.index"))


@bp.route("/<int:exam_id>", methods=["GET", "POST"])
@login_required
def edit(exam_id):
    exam = _get_exam(exam_id)
    if request.method == "GET":
        return render_template("exam_form.html", form=exam_form.form_from_exam(exam), exam=exam,
                               delete_blocked=exam_form.can_delete(exam))
    form = exam_form.parse_form(request.form)
    if not exam_form.validate(form, exam):
        return render_template("exam_form.html", form=form, exam=exam,
                               delete_blocked=exam_form.can_delete(exam)), 400
    exam_form.apply(form, exam)
    flash(f"Cambios de {exam.code} guardados.")
    return redirect(url_for("exams_admin.index"))


@bp.route("/<int:exam_id>/archivar", methods=["POST"])
@login_required
def toggle_archived(exam_id):
    exam = _get_exam(exam_id)
    if not exam.archived and Exam.query.filter_by(archived=False).count() == 1:
        flash(
            f"{exam.code} es el único examen sin archivar y la aplicación necesita uno en curso. "
            "Crea o desarchiva otro antes de archivar este."
        )
        return redirect(url_for("exams_admin.edit", exam_id=exam.id))
    exam.archived = not exam.archived
    if exam.archived:
        # Un examen archivado deja de ser el activo: si no, al desarchivarlo
        # meses después volvería a abrirse al entrar sin que nadie lo pidiera.
        User.query.filter_by(active_exam_id=exam.id).update({"active_exam_id": None})
    db.session.commit()
    flash(f"{exam.code} {'archivado' if exam.archived else 'desarchivado'}.")
    return redirect(url_for("exams_admin.index"))


@bp.route("/<int:exam_id>/borrar", methods=["POST"])
@login_required
def delete(exam_id):
    exam = _get_exam(exam_id)
    blocked = exam_form.can_delete(exam)
    if blocked:
        flash(blocked)
        return redirect(url_for("exams_admin.edit", exam_id=exam.id))
    if not exam.archived and Exam.query.filter_by(archived=False).count() == 1:
        flash(f"{exam.code} es el único examen sin archivar: crea otro antes de borrarlo.")
        return redirect(url_for("exams_admin.edit", exam_id=exam.id))
    code = exam.code
    exam_form.delete(exam)
    flash(f"Examen {code} borrado.")
    return redirect(url_for("exams_admin.index"))


def _kit_count():
    """Cuántas preguntas pedir: ?n= de la URL, acotado a algo razonable."""
    try:
        count = int(request.args.get("n", kit.DEFAULT_COUNT))
    except ValueError:
        count = kit.DEFAULT_COUNT
    return max(1, min(kit.MAX_COUNT, count))


@bp.route("/<int:exam_id>/kit")
@login_required
def generation_kit(exam_id):
    """Kit para generar preguntas con Claude (#20): se copia o se descarga."""
    exam = _get_exam(exam_id)
    count = _kit_count()
    return render_template("kit.html", exam=exam, count=count, max_count=kit.MAX_COUNT,
                           markdown=kit.build_kit(exam, count))


@bp.route("/<int:exam_id>/kit.md")
@login_required
def generation_kit_download(exam_id):
    exam = _get_exam(exam_id)
    response = Response(kit.build_kit(exam, _kit_count()), mimetype="text/markdown; charset=utf-8")
    response.headers["Content-Disposition"] = f"attachment; filename=kit-{exam.code.lower()}.md"
    return response
