"""Modelo de varios exámenes (issue #7).

La migración crea AIB-C01 con lo que antes vivía en app/sampling.py y
reasigna el banco. Estas pruebas comprueban que no se perdió nada por el
camino y que un segundo examen convive con el primero sin pisarlo.
"""
import json

import pytest

from app.extensions import db
from app.import_validation import validate_import
from app.models import Domain, Exam, Question, QuestionFormat, StudySession


def _aib(app):
    return Exam.query.filter_by(code="AIB-C01").one()


def test_la_migracion_crea_aib_c01_con_sus_dominios_y_formatos(app):
    with app.app_context():
        exam = _aib(app)
        assert exam.pass_threshold_pct == 72
        assert exam.minutes_per_question == 2
        assert [(d.number, d.short_name, d.weight) for d in exam.domains] == [
            (1, "Fundamentos", 24),
            (2, "Estrategia", 28),
            (3, "Gobernanza", 24),
            (4, "Transformación", 24),
        ]
        assert sum(d.weight for d in exam.domains) == 100
        assert [(f.option_count, f.correct_count) for f in exam.formats] == [(4, 1), (5, 2)]
        assert sum(f.target_share for f in exam.formats) == pytest.approx(1, abs=0.001)


def test_cada_pregunta_conserva_su_dominio(app):
    """El dominio de cada pregunta sembrada es el que dice el fichero de semilla."""
    with open("data/questions.seed.json", encoding="utf-8") as f:
        dominio_esperado = {item["id"]: item["dom"] for item in json.load(f)}

    with app.app_context():
        exam = _aib(app)
        preguntas = Question.query.filter_by(source="seed").all()
        assert len(preguntas) == len(dominio_esperado)
        for q in preguntas:
            assert q.exam_id == exam.id
            assert q.domain.exam_id == exam.id
            assert q.domain.number == dominio_esperado[q.ext_id], q.ext_id


@pytest.fixture
def segundo_examen(app):
    """Un examen de tres dominios con pesos distintos, borrado al terminar."""
    with app.app_context():
        exam = Exam(code="PRUEBA-1", name="Examen de prueba", pass_threshold_pct=70, minutes_per_question=1)
        db.session.add(exam)
        db.session.flush()
        for number, weight in ((1, 50), (2, 30), (3, 20)):
            db.session.add(Domain(exam_id=exam.id, number=number, name=f"Dominio {number}",
                                  short_name=f"D{number}", weight=weight))
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=4, correct_count=1))
        db.session.commit()
        exam_id = exam.id
    yield exam_id
    with app.app_context():
        Question.query.filter_by(exam_id=exam_id).delete()
        QuestionFormat.query.filter_by(exam_id=exam_id).delete()
        Domain.query.filter_by(exam_id=exam_id).delete()
        db.session.delete(db.session.get(Exam, exam_id))
        db.session.commit()


def _pregunta(ext_id, dom):
    return {
        "id": ext_id, "dom": dom, "hab": "1.1.1", "t": "s",
        "q": "Enunciado de prueba", "o": ["A", "B", "C", "D"], "ok": [0], "w": "Explicación de prueba",
    }


def test_el_ext_id_es_unico_dentro_de_cada_examen_no_en_todo_el_banco(app, segundo_examen):
    with app.app_context():
        aib = _aib(app)
        otro = db.session.get(Exam, segundo_examen)
        ext_id_de_aib = Question.query.filter_by(exam_id=aib.id).first().ext_id

        # En el otro examen ese mismo id está libre…
        resultado = validate_import([_pregunta(ext_id_de_aib, 1)], exam=otro)
        assert len(resultado.accepted) == 1, resultado.rejected
        item = resultado.accepted[0]
        assert item["exam_id"] == otro.id
        assert item["domain_id"] == next(d.id for d in otro.domains if d.number == 1)
        db.session.add(Question(**item))
        db.session.commit()

        # …pero en AIB-C01 ya existe.
        resultado = validate_import([_pregunta(ext_id_de_aib, 1)], exam=aib)
        assert not resultado.accepted
        assert "ya existe" in resultado.rejected[0][1]


def test_un_dominio_que_el_examen_no_tiene_se_rechaza_diciendo_cuales_admite(app, segundo_examen):
    with app.app_context():
        otro = db.session.get(Exam, segundo_examen)
        resultado = validate_import([_pregunta("x-01", 4)], exam=otro)
        assert not resultado.accepted
        motivo = resultado.rejected[0][1]
        assert "PRUEBA-1" in motivo and "1, 2, 3" in motivo


def test_la_tanda_queda_asociada_al_examen(app, logged_in):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    with app.app_context():
        tanda = db.session.get(StudySession, inicio["study_session_id"])
        try:
            assert tanda.exam_id == _aib(app).id
        finally:
            db.session.delete(tanda)
            db.session.commit()


def test_una_tanda_empezada_con_la_version_anterior_se_descarta(logged_in):
    """Tras desplegar, una pestaña con una tanda vieja en la cookie (cola de ext_id)
    no puede romper /answer: se trata como si no hubiera tanda."""
    with logged_in.session_transaction() as sesion:
        sesion["practice_queue"] = {
            "study_session_id": 1, "mode": "rapida", "domain": None,
            "queue": ["d1-01"], "option_orders": {"d1-01": [0, 1, 2, 3]}, "index": 0, "results": [],
        }
    respuesta = logged_in.post("/api/session/answer", json={"selected": [0]})
    assert respuesta.status_code == 409
    assert "tanda" in respuesta.get_json()["error"]
