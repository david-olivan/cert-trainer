"""Borrado del progreso: sesiones de estudio e intentos.

Vive aparte de las vistas y del CLI porque lo usan los dos: el comando
`flask db-reset-progress` y el botón de la barra superior. El banco de
preguntas es contenido curado y nunca se toca desde aquí.
"""
from app.extensions import db
from app.models import Attempt, ReviewState, StudySession


def reset_progress():
    """Borra todos los intentos y sesiones. Devuelve cuántos de cada.

    También el estado FSRS de cada pregunta, que se deriva de los intentos:
    sin ellos, las preguntas vuelven a estar sin ver.
    """
    ReviewState.query.delete(synchronize_session=False)
    attempts = Attempt.query.delete(synchronize_session=False)
    sessions = StudySession.query.delete(synchronize_session=False)
    db.session.commit()
    return {"attempts": attempts, "sessions": sessions}
