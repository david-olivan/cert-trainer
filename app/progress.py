"""Borrado del progreso: sesiones de estudio e intentos.

Vive aparte de las vistas y del CLI porque lo usan los dos: el comando
`flask db-reset-progress` y el botón de la barra superior. El banco de
preguntas es contenido curado y nunca se toca desde aquí.
"""
from app.extensions import db
from app.models import Attempt, StudySession


def reset_progress():
    """Borra todos los intentos y sesiones. Devuelve cuántos de cada."""
    attempts = Attempt.query.delete(synchronize_session=False)
    sessions = StudySession.query.delete(synchronize_session=False)
    db.session.commit()
    return {"attempts": attempts, "sessions": sessions}
