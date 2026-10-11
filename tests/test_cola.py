"""La cola de la tanda vive en la base, no en la cookie (issue #18).

La cookie de sesión de Flask está firmada pero viaja entera en cada
petición, y los navegadores la descartan en silencio a partir de 4 kB.
Con la cola dentro, un simulacro con más de ~440 preguntas se quedaba en
blanco sin ningún error.
"""
import pytest

from app.extensions import db
from app.models import Attempt, Domain, Exam, FsrsParameters, Question, QuestionFormat, ReviewState, StudySession

PREGUNTAS = 500


def _cookie_de_sesion(respuesta):
    for cabecera in respuesta.headers.getlist("Set-Cookie"):
        if cabecera.startswith("session="):
            return cabecera.split(";", 1)[0][len("session="):]
    return None


@pytest.fixture
def examen_grande(app):
    """Un examen de 500 preguntas como examen en curso; AIB-C01 se archiva mientras."""
    with app.app_context():
        aib = Exam.query.filter_by(code="AIB-C01").one()
        exam = Exam(code="GRANDE", name="Examen de 500 preguntas", pass_threshold_pct=70, minutes_per_question=1)
        db.session.add(exam)
        db.session.flush()
        domain = Domain(exam_id=exam.id, number=1, name="Único", short_name="Único", weight=100)
        db.session.add(domain)
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=4, correct_count=1))
        db.session.flush()
        db.session.add_all(
            Question(exam_id=exam.id, domain_id=domain.id, ext_id=f"g-{i:03}", skill="1.1", type="s",
                     stem=f"Enunciado {i}", options=["A", "B", "C", "D"], correct=[0], explanation="Porque sí.")
            for i in range(PREGUNTAS)
        )
        aib.archived = True
        db.session.commit()
        exam_id, aib_id = exam.id, aib.id
    try:
        yield exam_id
    finally:
        with app.app_context():
            session_ids = [s.id for s in StudySession.query.filter_by(exam_id=exam_id)]
            question_ids = [q.id for q in Question.query.filter_by(exam_id=exam_id)]
            if session_ids:
                Attempt.query.filter(Attempt.session_id.in_(session_ids)).delete(synchronize_session=False)
            ReviewState.query.filter(ReviewState.question_id.in_(question_ids)).delete(synchronize_session=False)
            StudySession.query.filter_by(exam_id=exam_id).delete()
            Question.query.filter_by(exam_id=exam_id).delete()
            QuestionFormat.query.filter_by(exam_id=exam_id).delete()
            FsrsParameters.query.filter_by(exam_id=exam_id).delete()
            Domain.query.filter_by(exam_id=exam_id).delete()
            db.session.delete(db.session.get(Exam, exam_id))
            db.session.get(Exam, aib_id).archived = False
            db.session.commit()


def test_un_simulacro_de_500_preguntas_no_infla_la_cookie(logged_in, examen_grande):
    respuesta = logged_in.post("/api/session/start", json={"mode": "simulacro"})
    assert respuesta.status_code == 200, respuesta.data
    assert respuesta.get_json()["total"] == PREGUNTAS

    cookie = _cookie_de_sesion(respuesta)
    assert cookie is not None
    assert len(cookie) < 1024, f"la cookie de sesión ocupa {len(cookie)} bytes"

    # Y la tanda funciona: responder avanza y la siguiente pregunta llega.
    assert logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"}).status_code == 200
    siguiente = logged_in.get("/api/session/next").get_json()
    assert siguiente["index"] == 1 and siguiente["total"] == PREGUNTAS


@pytest.fixture
def sin_progreso(app):
    yield
    app.test_cli_runner().invoke(args=["db-reset-progress", "--yes"])


def test_abandonar_a_mitad_deja_las_respuestas_y_la_posicion(app, logged_in, sin_progreso):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    for _ in range(3):
        logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})

    # Se cierra el navegador: un cliente nuevo no tiene la cookie de la
    # tanda, pero nada de lo respondido se ha perdido.
    otro_navegador = app.test_client()
    assert otro_navegador.get("/api/session/next").status_code in (302, 401, 409)
    with app.app_context():
        tanda = db.session.get(StudySession, inicio["study_session_id"])
        assert Attempt.query.filter_by(session_id=tanda.id).count() == 3
        assert tanda.position == 3
        assert len(tanda.queue) == inicio["total"]
        assert tanda.finished_at is None


def test_una_tanda_cerrada_no_admite_mas_respuestas(app, logged_in, sin_progreso):
    logged_in.post("/api/session/start", json={"mode": "rapida"})
    logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
    resultado = logged_in.post("/api/session/finish").get_json()
    assert resultado["answered"] == 1

    respuesta = logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
    assert respuesta.status_code == 409
    assert logged_in.get("/api/session/next").status_code == 409


def test_el_resultado_sale_de_las_respuestas_guardadas(app, logged_in, sin_progreso):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    for _ in range(4):
        logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
    resultado = logged_in.post("/api/session/finish").get_json()

    with app.app_context():
        intentos = Attempt.query.filter_by(session_id=inicio["study_session_id"]).all()
        aciertos = sum(1 for a in intentos if a.is_correct)
        tanda = db.session.get(StudySession, inicio["study_session_id"])
        assert resultado["answered"] == 4 == len(intentos)
        assert resultado["correct"] == aciertos
        assert tanda.score_pct == resultado["score_pct"]
        assert tanda.question_count == 4
