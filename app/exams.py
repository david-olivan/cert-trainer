"""Qué examen se está preparando (issue #8).

El examen en curso se decide en este orden:
1. El que se eligió para estudiar puntualmente en este navegador
   (sesión de Flask), si no está archivado.
2. El examen activo del usuario, guardado en la base para que valga igual
   en el móvil y en el portátil, si no está archivado.
3. El primer examen sin archivar.

Fuera de una petición (comandos de consola) no hay sesión de navegador:
cuenta el examen activo del usuario único, y si no, el primero sin archivar.
"""
from flask import has_request_context, session
from flask_login import current_user

from app.extensions import db
from app.models import Domain, Exam, User

SESSION_EXAM_KEY = "exam_id"


class NoExamError(RuntimeError):
    """No hay ningún examen sin archivar sobre el que trabajar."""


def _usable(exam_id):
    if exam_id is None:
        return None
    exam = db.session.get(Exam, exam_id)
    return exam if exam is not None and not exam.archived else None


def _user():
    if has_request_context() and current_user.is_authenticated:
        return current_user
    return User.query.order_by(User.id).first()


def active_exam():
    """El examen fijado como activo, o None si no hay o está archivado."""
    user = _user()
    return _usable(user.active_exam_id) if user is not None else None


def session_exam():
    """El examen elegido puntualmente en este navegador, o None."""
    if not has_request_context():
        return None
    return _usable(session.get(SESSION_EXAM_KEY))


def current_exam():
    exam = session_exam() or active_exam()
    if exam is None:
        exam = Exam.query.filter_by(archived=False).order_by(Exam.id).first()
    if exam is None:
        raise NoExamError(
            "No hay ningún examen sin archivar. Si acabas de desplegar, ejecuta "
            "`flask db upgrade`, que crea AIB-C01; si los archivaste todos, "
            "desarchiva uno en «Exámenes»."
        )
    return exam


def domain_by_number(exam):
    """{número: Domain} de un examen."""
    return {d.number: d for d in Domain.query.filter_by(exam_id=exam.id)}
