"""Examen activo y examen en curso (issue #8)."""
import pytest

from app.extensions import db
from app.models import Attempt, Domain, Exam, FsrsParameters, Question, QuestionFormat, ReviewState, StudySession, User
from tests.conftest import PASSWORD

CODIGO = "PRUEBA-ACT"


@pytest.fixture
def otro_examen(app):
    """Un segundo examen con dos preguntas; al terminar se borra y el usuario queda sin examen activo."""
    with app.app_context():
        exam = Exam(code=CODIGO, name="Examen para elegir", pass_threshold_pct=65, minutes_per_question=1)
        db.session.add(exam)
        db.session.flush()
        domain = Domain(exam_id=exam.id, number=1, name="Único dominio", short_name="Único", weight=100)
        db.session.add(domain)
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=3, correct_count=1))
        db.session.flush()
        for i in range(2):
            db.session.add(Question(exam_id=exam.id, domain_id=domain.id, ext_id=f"act-{i}", skill="1.1", type="s",
                                    stem=f"Pregunta {i}", options=["A", "B", "C"], correct=[0], explanation="Porque sí."))
        db.session.commit()
        exam_id = exam.id
    yield exam_id
    with app.app_context():
        User.query.update({"active_exam_id": None})
        session_ids = [s.id for s in StudySession.query.filter_by(exam_id=exam_id)]
        if session_ids:
            Attempt.query.filter(Attempt.session_id.in_(session_ids)).delete(synchronize_session=False)
        question_ids = [q.id for q in Question.query.filter_by(exam_id=exam_id)]
        if question_ids:
            ReviewState.query.filter(ReviewState.question_id.in_(question_ids)).delete(synchronize_session=False)
        StudySession.query.filter_by(exam_id=exam_id).delete()
        Question.query.filter_by(exam_id=exam_id).delete()
        QuestionFormat.query.filter_by(exam_id=exam_id).delete()
        FsrsParameters.query.filter_by(exam_id=exam_id).delete()
        Domain.query.filter_by(exam_id=exam_id).delete()
        exam = db.session.get(Exam, exam_id)
        if exam is not None:
            db.session.delete(exam)
        db.session.commit()


def _nuevo_navegador(app):
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": PASSWORD})
    return client


def _portada(client):
    return client.get("/").get_data(as_text=True)


def test_sin_examen_activo_se_estudia_el_primero_y_se_ofrece_cambiar(logged_in, otro_examen):
    html = _portada(logged_in)
    assert "AIB-C01 · 44 preguntas" in html
    assert "Cambiar de examen" in html and CODIGO in html


def test_el_examen_activo_vale_en_cualquier_navegador(app, logged_in, otro_examen):
    respuesta = logged_in.post(f"/examen/{otro_examen}/activar", follow_redirects=True)
    html = respuesta.get_data(as_text=True)
    assert f"{CODIGO} es tu examen activo" in html
    assert f"{CODIGO} · 2 preguntas" in html
    assert f"<span>{CODIGO}</span>" in html, "la barra superior muestra el examen en curso"
    assert f"{CODIGO} · 2 preguntas" in _portada(_nuevo_navegador(app))


def test_estudiar_otro_examen_solo_cambia_este_navegador(app, logged_in, otro_examen):
    logged_in.post(f"/examen/{otro_examen}/activar")
    with app.app_context():
        aib = Exam.query.filter_by(code="AIB-C01").one().id

    html = logged_in.post(f"/examen/{aib}/estudiar", follow_redirects=True).get_data(as_text=True)
    assert "AIB-C01 · 44 preguntas" in html
    assert f"tu examen activo es {CODIGO}" in html
    assert f"{CODIGO} · 2 preguntas" in _portada(_nuevo_navegador(app)), "el otro navegador sigue en el activo"

    html = logged_in.post("/examen/volver-al-activo", follow_redirects=True).get_data(as_text=True)
    assert f"{CODIGO} · 2 preguntas" in html


def test_la_tanda_queda_en_el_examen_elegido(app, logged_in, otro_examen):
    logged_in.post(f"/examen/{otro_examen}/activar")
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    assert inicio["total"] == 2
    assert inicio["minutes_per_question"] == 1
    with app.app_context():
        assert db.session.get(StudySession, inicio["study_session_id"]).exam_id == otro_examen


def test_archivar_el_activo_lo_deja_de_ser(app, logged_in, otro_examen):
    logged_in.post(f"/examen/{otro_examen}/activar")
    logged_in.post(f"/examenes/{otro_examen}/archivar")
    with app.app_context():
        assert User.query.one().active_exam_id is None
    assert "AIB-C01 · 44 preguntas" in _portada(logged_in)

    # Archivado, ni se puede estudiar ni fijar.
    html = logged_in.post(f"/examen/{otro_examen}/estudiar", follow_redirects=True).get_data(as_text=True)
    assert "está archivado" in html


def test_borrar_el_examen_activo(app, logged_in, otro_examen):
    with app.app_context():
        Question.query.filter_by(exam_id=otro_examen).delete()
        db.session.commit()
    logged_in.post(f"/examen/{otro_examen}/activar")
    logged_in.post(f"/examenes/{otro_examen}/borrar")
    with app.app_context():
        assert db.session.get(Exam, otro_examen) is None
        assert User.query.one().active_exam_id is None
    assert "AIB-C01 · 44 preguntas" in _portada(logged_in)


def test_la_consola_trabaja_sobre_el_examen_activo(app, logged_in, otro_examen, tmp_path):
    """Sin navegador no hay elección puntual: cuenta el examen activo del usuario."""
    import json

    logged_in.post(f"/examen/{otro_examen}/activar")
    fichero = tmp_path / "export.json"
    resultado = app.test_cli_runner().invoke(args=["questions", "export", str(fichero)])
    assert resultado.exit_code == 0, resultado.output
    assert [q["id"] for q in json.loads(fichero.read_text())] == ["act-0", "act-1"]
