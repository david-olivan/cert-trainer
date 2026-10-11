"""Un examen que no es AIB-C01 funciona de punta a punta (issue #15).

Tres dominios con pesos 50/30/20, formatos propios (3 opciones con 1
correcta y 4 con 2), otro umbral y otro ritmo. Si algo del código sigue
suponiendo los cuatro dominios de AIB-C01, sus pesos o su 72 %, aquí se
nota. Para que sea el examen en curso, AIB-C01 se archiva durante la
prueba y se restaura al terminar.
"""
from collections import Counter

import pytest

from app.extensions import db
from app.models import Attempt, Domain, Exam, FsrsParameters, Question, QuestionFormat, ReviewState, StudySession
from app.sampling import weighted_sample

PESOS = {1: 50, 2: 30, 3: 20}


def _pregunta(ext_id, dom, opciones=3, correctas=(0,)):
    return {
        "id": ext_id, "dom": dom, "hab": f"{dom}.1",
        "q": f"Enunciado de prueba {ext_id}", "o": [f"Opción {i}" for i in range(opciones)],
        "ok": list(correctas), "w": "Explicación de prueba",
    }


# 10 + 6 + 4 de una correcta, y una de dos correctas en el dominio 1.
BLOQUE_VALIDO = (
    [_pregunta(f"a-{i:02}", 1) for i in range(10)]
    + [_pregunta(f"b-{i:02}", 2) for i in range(6)]
    + [_pregunta(f"c-{i:02}", 3) for i in range(4)]
    + [_pregunta("a-m1", 1, opciones=4, correctas=(0, 2))]
)


@pytest.fixture
def otro_examen(app):
    with app.app_context():
        aib = Exam.query.filter_by(code="AIB-C01").one()
        exam = Exam(code="PRUEBA-2", name="Examen de tres dominios", pass_threshold_pct=60,
                    minutes_per_question=1)
        db.session.add(exam)
        db.session.flush()
        for number, weight in PESOS.items():
            db.session.add(Domain(exam_id=exam.id, number=number, name=f"Dominio largo {number}",
                                  short_name=f"Corto{number}", weight=weight))
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=3, correct_count=1))
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=4, correct_count=2))
        aib.archived = True
        db.session.commit()
        exam_id, aib_id = exam.id, aib.id
    try:
        yield exam_id
    finally:
        with app.app_context():
            session_ids = [s.id for s in StudySession.query.filter_by(exam_id=exam_id)]
            if session_ids:
                Attempt.query.filter(Attempt.session_id.in_(session_ids)).delete(synchronize_session=False)
            StudySession.query.filter_by(exam_id=exam_id).delete()
            question_ids = [q.id for q in Question.query.filter_by(exam_id=exam_id)]
            if question_ids:
                ReviewState.query.filter(ReviewState.question_id.in_(question_ids)).delete(synchronize_session=False)
            FsrsParameters.query.filter_by(exam_id=exam_id).delete()
            Question.query.filter_by(exam_id=exam_id).delete()
            QuestionFormat.query.filter_by(exam_id=exam_id).delete()
            Domain.query.filter_by(exam_id=exam_id).delete()
            db.session.delete(db.session.get(Exam, exam_id))
            db.session.get(Exam, aib_id).archived = False
            db.session.commit()


@pytest.fixture
def con_preguntas(logged_in, otro_examen):
    import json

    respuesta = logged_in.post("/preguntas/confirm", json={"raw": json.dumps(BLOQUE_VALIDO)})
    assert respuesta.status_code == 200, respuesta.data
    assert respuesta.get_json()["inserted"] == len(BLOQUE_VALIDO), respuesta.get_json()["rejected"]
    return otro_examen


def test_la_importacion_valida_contra_los_dominios_y_formatos_del_examen(logged_in, otro_examen):
    import json

    bloque = [
        _pregunta("ok-1", 3),
        _pregunta("dom-4", 4),  # PRUEBA-2 no tiene dominio 4
        _pregunta("formato-aib", 1, opciones=4, correctas=(1,)),  # 4/1 es de AIB-C01, no de este
        {**_pregunta("t-mal", 1), "t": "m"},  # dice múltiple con una sola correcta
    ]
    cuerpo = logged_in.post("/preguntas/preview", json={"raw": json.dumps(bloque)}).get_json()
    assert [a["ext_id"] for a in cuerpo["accepted"]] == ["ok-1"]
    assert cuerpo["accepted"][0]["type"] == "s"
    motivos = {r["identifier"]: r["reason"] for r in cuerpo["rejected"]}
    assert "no es un dominio de PRUEBA-2 (admite 1, 2, 3)" in motivos['"dom-4"']
    assert "no es un formato de PRUEBA-2" in motivos['"formato-aib"']
    assert "3 opciones con 1 correcta, 4 opciones con 2 correctas" in motivos['"formato-aib"']
    assert "campo 't'" in motivos['"t-mal"']


def test_el_muestreo_respeta_los_pesos_del_examen(app, con_preguntas):
    with app.app_context():
        exam = db.session.get(Exam, con_preguntas)
        muestra = weighted_sample(exam, 10)
        por_dominio = Counter(q.domain.number for q in muestra)
        assert por_dominio == {1: 5, 2: 3, 3: 2}


def test_la_portada_pinta_los_dominios_y_el_umbral_del_examen(logged_in, con_preguntas):
    html = logged_in.get("/").get_data(as_text=True)
    for number in PESOS:
        assert f"Corto{number}" in html
        assert f"Dominio largo {number}" in html
    assert "Fundamentos" not in html, "se cuela un dominio de AIB-C01"
    assert "umbral orientativo 60 %" in html
    assert "1 min cada una" in html


def test_una_tanda_completa_en_el_otro_examen(app, logged_in, con_preguntas):
    assert '"1": "Corto1"' in logged_in.get("/tanda?mode=rapida").get_data(as_text=True)

    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    assert inicio["total"] == 10
    assert inicio["minutes_per_question"] == 1
    assert inicio["question"]["domain_short"].startswith("Corto")

    for _ in range(inicio["total"]):
        assert logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"}).status_code == 200
        siguiente = logged_in.get("/api/session/next").get_json()
    assert siguiente["done"] is True

    resultado = logged_in.post("/api/session/finish").get_json()
    assert resultado["answered"] == 10
    assert set(resultado["per_domain_pct"]) <= {"1", "2", "3"}

    with app.app_context():
        tanda = db.session.get(StudySession, inicio["study_session_id"])
        assert tanda.exam_id == con_preguntas


def test_un_dominio_que_el_examen_no_tiene_no_arranca_tanda(logged_in, con_preguntas):
    respuesta = logged_in.post("/api/session/start", json={"mode": "dominio", "domain": 4})
    assert respuesta.status_code == 400
    assert "PRUEBA-2 no tiene el dominio 4" in respuesta.get_json()["error"]

    respuesta = logged_in.post("/api/session/start", json={"mode": "dominio", "domain": 3})
    assert respuesta.status_code == 200
    assert respuesta.get_json()["total"] == 4
