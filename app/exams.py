"""Qué examen se está preparando.

Hasta que exista el examen activo (issue #8), la aplicación trabaja sobre
el primer examen sin archivar, que hoy es AIB-C01: lo crea la migración
que introduce los exámenes (issue #7).
"""
from app.models import Domain, Exam


class NoExamError(RuntimeError):
    """No hay ningún examen sin archivar sobre el que trabajar."""


def current_exam():
    exam = Exam.query.filter_by(archived=False).order_by(Exam.id).first()
    if exam is None:
        raise NoExamError(
            "No hay ningún examen dado de alta. Ejecuta `flask db upgrade`: la "
            "migración de varios exámenes crea AIB-C01."
        )
    return exam


def domain_by_number(exam):
    """{número: Domain} de un examen."""
    return {d.number: d for d in Domain.query.filter_by(exam_id=exam.id)}
