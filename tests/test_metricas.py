"""Panel de métricas (issue #21)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.metrics import dashboard, readiness
from app.models import Attempt, Domain, Exam, FsrsParameters, Question, QuestionFormat, ReviewState, StudySession
from app.srs import rebuild, retrievability, scheduled_dues

CODIGO = "MET-1"
# En el pasado y a mediodía en Madrid: los días locales no dependen de cuándo corra la prueba.
AHORA = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
OPCIONES = ["Opción uno", "Opción dos", "Opción tres"]


@pytest.fixture
def examen(app):
    """Dos dominios (60/40) y seis preguntas de 3 opciones con la correcta en la 0, sin respuestas."""
    with app.app_context():
        exam = Exam(code=CODIGO, name="Examen de métricas", pass_threshold_pct=70, minutes_per_question=2,
                    exam_date=date(2026, 11, 30))
        db.session.add(exam)
        db.session.flush()
        d1 = Domain(exam_id=exam.id, number=1, name="Primero", short_name="Uno", weight=60)
        d2 = Domain(exam_id=exam.id, number=2, name="Segundo", short_name="Dos", weight=40)
        db.session.add_all([d1, d2])
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=3, correct_count=1, target_share=1.0))
        db.session.flush()
        for i, dom in enumerate((d1, d1, d1, d1, d2, d2), start=1):
            db.session.add(Question(exam_id=exam.id, domain_id=dom.id, ext_id=f"m{i}", skill=f"{dom.number}.1",
                                    type="s", stem=f"Enunciado {i}", options=OPCIONES, correct=[0],
                                    explanation=f"Explicación {i}"))
        db.session.commit()
        exam_id = exam.id
    yield exam_id
    with app.app_context():
        session_ids = [s.id for s in StudySession.query.filter_by(exam_id=exam_id)]
        if session_ids:
            Attempt.query.filter(Attempt.session_id.in_(session_ids)).delete(synchronize_session=False)
        question_ids = [q.id for q in Question.query.filter_by(exam_id=exam_id)]
        ReviewState.query.filter(ReviewState.question_id.in_(question_ids)).delete(synchronize_session=False)
        StudySession.query.filter_by(exam_id=exam_id).delete()
        Question.query.filter_by(exam_id=exam_id).delete()
        QuestionFormat.query.filter_by(exam_id=exam_id).delete()
        FsrsParameters.query.filter_by(exam_id=exam_id).delete()
        Domain.query.filter_by(exam_id=exam_id).delete()
        db.session.delete(db.session.get(Exam, exam_id))
        db.session.commit()


# (pregunta, días atrás, elegida, confianza, segundos, orden mostrado, primero piensa)
RESPUESTAS = [
    ("m1", 3, 0, "sure", 20, [2, 0, 1], False),
    ("m2", 2, 1, "sure", 40, [0, 1, 2], False),
    ("m1", 1, 0, "sure", 40, [0, 1, 2], False),
    ("m2", 1, 1, "sure", 200, [0, 1, 2], False),
    ("m3", 1, 0, "unsure", 200, [0, 1, 2], True),
    ("m5", 1, 2, "unsure", 50, [0, 1, 2], False),
    ("m1", 0, 0, "sure", 40, [0, 1, 2], False),
]


@pytest.fixture
def con_respuestas(app, examen):
    with app.app_context():
        ids = {q.ext_id: q.id for q in Question.query.filter_by(exam_id=examen)}
        sesion = StudySession(exam_id=examen, mode="rapida", question_count=len(RESPUESTAS))
        db.session.add(sesion)
        db.session.flush()
        for ext_id, dias, elegida, confianza, segundos, orden, piensa in RESPUESTAS:
            db.session.add(Attempt(
                question_id=ids[ext_id], session_id=sesion.id, selected=[elegida], is_correct=elegida == 0,
                seconds_spent=segundos, answered_at=AHORA - timedelta(days=dias), confidence=confianza,
                hint_used=False, option_order=orden, recall_first=piensa,
            ))
        db.session.commit()
        rebuild([db.session.get(Exam, examen)], now=AHORA)
    return examen


def test_sin_respuestas_la_pagina_lo_dice(app, logged_in, examen):
    logged_in.post(f"/examen/{examen}/estudiar")
    try:
        html = logged_in.get("/metricas").get_data(as_text=True)
        assert f"Aún no hay respuestas en {CODIGO}" in html
        with app.app_context():
            r = readiness(db.session.get(Exam, examen))
        assert r[1]["pct"] is None and r["overall"] is None
    finally:
        logged_in.post("/examen/volver-al-activo")


def test_acierto_en_primera_vista(app, con_respuestas):
    with app.app_context():
        datos = dashboard(db.session.get(Exam, con_respuestas), AHORA)
    fs = datos["first_sight"]
    # Dominio 1: m1 bien, m2 mal, m3 bien. Dominio 2: m5 mal.
    assert (fs["by_domain"][1]["correct"], fs["by_domain"][1]["total"]) == (2, 3)
    assert (fs["by_domain"][2]["correct"], fs["by_domain"][2]["total"]) == (0, 1)
    assert fs["overall"]["pct"] == 50
    assert datos["questions_seen"] == 4 and datos["answers"] == 7


def test_el_medidor_mezcla_fsrs_y_primera_vista(app, con_respuestas):
    """Las vistas cuentan con su probabilidad FSRS; las no vistas, con el acierto en primera vista."""
    with app.app_context():
        exam = db.session.get(Exam, con_respuestas)
        r_por_pregunta = retrievability(exam, AHORA)
        ids = {q.ext_id: q.id for q in Question.query.filter_by(exam_id=exam.id)}
        r = readiness(exam, AHORA)
    vistas_d1 = [r_por_pregunta[ids[e]] for e in ("m1", "m2", "m3")]
    assert r[1] == {"pct": round((sum(vistas_d1) + 1 * 2 / 3) / 4 * 100), "seen": 3, "total": 4}
    assert r[2] == {"pct": round((r_por_pregunta[ids["m5"]] + 1 * 0) / 2 * 100), "seen": 1, "total": 2}
    assert r["overall"] == round((60 * r[1]["pct"] + 40 * r[2]["pct"]) / 100)


def test_la_proyeccion_es_un_suelo(app, con_respuestas):
    """Sin más repasos, la probabilidad solo baja: el día del examen no puede superar a la de hoy."""
    with app.app_context():
        datos = dashboard(db.session.get(Exam, con_respuestas), AHORA)
    p = datos["projection"]
    assert p["date"] == date(2026, 11, 30) and p["days"] == 56
    assert p[1]["pct"] <= datos["readiness"][1]["pct"]
    assert p["overall"] <= datos["readiness"]["overall"]


def test_fallos_seguros_distractores_y_nunca_falladas(app, con_respuestas):
    with app.app_context():
        datos = dashboard(db.session.get(Exam, con_respuestas), AHORA)
        seguros = [(e["question"].ext_id, e["count"], e["picked"]) for e in datos["sure_failures"]["questions"]]
        distractores = [(e["question"].ext_id, e["option"], e["count"], e["answered"]) for e in datos["distractors"]]
        nunca = [(e["question"].ext_id, e["answered"]) for e in datos["never_failed"]]
    assert seguros == [("m2", 2, ["Opción dos"])], "el fallo con «dudo» de m5 no es un error de concepto"
    assert datos["sure_failures"]["total"] == 2
    assert distractores == [("m2", "Opción dos", 2, 2)], "elegir una vez «Opción tres» en m5 no es un patrón"
    assert nunca == [("m1", 3)]


def test_tiempos_y_aciertos_lentos(app, con_respuestas):
    with app.app_context():
        t = dashboard(db.session.get(Exam, con_respuestas), AHORA)["timing"]
        lentos = [(e["question"].ext_id, e["count"]) for e in t["slow"]]
    # Menos de 20 respuestas: referencia de 60 s, lento por encima de 90.
    assert (t["reference"], t["slow_limit"]) == (60, 90)
    assert lentos == [("m3", 1)], "m2 tardó 200 s pero falló: no es un acierto lento"
    assert t["median"] == 40 and t["budget"] == 120
    assert sum(b["count"] for b in t["buckets"]) == 7
    assert t["over_budget"]["correct"] == 2


def test_sesgo_de_posicion(app, con_respuestas):
    with app.app_context():
        (grupo,) = dashboard(db.session.get(Exam, con_respuestas), AHORA)["position_bias"]
    assert grupo["options"] == 3 and grupo["answers"] == 7
    # En la primera respuesta a m1 la opción original 0 se mostró en la posición B.
    assert [p["chosen"] for p in grupo["positions"]] == [43, 43, 14]
    assert [p["correct"] for p in grupo["positions"]] == [86, 14, 0]


def test_primero_piensa_frente_a_sin(app, con_respuestas):
    with app.app_context():
        rf = dashboard(db.session.get(Exam, con_respuestas), AHORA)["recall_first"]
    assert (rf[True]["correct"], rf[True]["total"]) == (1, 1)
    assert (rf[False]["correct"], rf[False]["total"]) == (3, 6)


def test_habito_y_carga(app, con_respuestas):
    with app.app_context():
        exam = db.session.get(Exam, con_respuestas)
        h = dashboard(exam, AHORA)["habit"]
        assert len(scheduled_dues(exam)) == 7
    por_dia = {e["day"]: e for e in h["per_day"]}
    assert (por_dia[date(2026, 10, 4)]["repeat"], por_dia[date(2026, 10, 4)]["new"]) == (2, 2)
    assert h["answers"] == 7 and h["active_days"] == 4
    carga = {e["day"]: e for e in h["load"]}
    # m2 se falló el día 3: FSRS lo programó para el 4, y ese día se repasaron dos.
    assert carga[date(2026, 10, 4)]["due"] >= 1
    assert carga[date(2026, 10, 4)]["done"] == 2
    assert h["load_done"] == 3


def test_la_pagina_y_la_portada(app, logged_in, con_respuestas):
    logged_in.post(f"/examen/{con_respuestas}/estudiar")
    try:
        html = logged_in.get("/metricas").get_data(as_text=True)
        for texto in ("Acierto en primera vista", "Fallos con «seguro» · 2", "Sesgo de posición",
                      "Distractores más elegidos", "Nunca falladas · 1", "Aciertos lentos · 1",
                      "Proyección al examen", "no predicciones de nota", "Opción dos"):
            assert texto in html, texto
        portada = logged_in.get("/").get_data(as_text=True)
        assert "Probabilidad media de acertar hoy" in portada
        assert "Ver todas las métricas" in portada
    finally:
        logged_in.post("/examen/volver-al-activo")
