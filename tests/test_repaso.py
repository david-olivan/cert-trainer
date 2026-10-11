"""«Repaso de hoy» (issue #17)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.extensions import db
from app.models import Attempt, Exam, Question, ReviewState, StudySession
from app.srs import daily_review, day_end, review_summary

MADRID = ZoneInfo("Europe/Madrid")
# Miércoles 14 de octubre de 2026, 08:00 UTC = 10:00 en Madrid (horario de verano).
AHORA = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "ahora, fin_del_dia",
    [
        # 01:30 del 12 en Madrid: «hoy» es el 12 y acaba a las 22:00 UTC.
        (datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc), datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)),
        # En invierno, Madrid va a UTC+1.
        (datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc), datetime(2026, 12, 1, 23, 0, tzinfo=timezone.utc)),
    ],
)
def test_hoy_es_el_dia_local(ahora, fin_del_dia):
    assert day_end(ahora, MADRID) == fin_del_dia


@pytest.fixture
def examen(app):
    """AIB-C01 sin progreso, con el cupo de nuevas restaurado al terminar."""
    runner = app.test_cli_runner()
    runner.invoke(args=["db-reset-progress", "--yes"])
    with app.app_context():
        exam = Exam.query.filter_by(code="AIB-C01").one()
        cupo_original = exam.new_per_day
    yield
    runner.invoke(args=["db-reset-progress", "--yes"])
    with app.app_context():
        Exam.query.filter_by(code="AIB-C01").one().new_per_day = cupo_original
        db.session.commit()


def _estado(question, due, last_review, stability):
    db.session.add(ReviewState(question_id=question.id, state=2, step=None, stability=stability,
                               difficulty=5.0, due=due, last_review=last_review))


def _preguntas(exam, n):
    return Question.query.filter_by(exam_id=exam.id, active=True).order_by(Question.id).limit(n).all()


def test_la_cola_de_hoy(app, examen):
    with app.app_context():
        exam = Exam.query.filter_by(code="AIB-C01").one()
        exam.new_per_day = 3
        q1, q2, q3, q4 = _preguntas(exam, 4)
        # Atrasada y poco estable: la que menos probabilidad tiene de acertarse.
        _estado(q1, AHORA - timedelta(days=2), AHORA - timedelta(days=10), stability=3)
        # Vence esta tarde (16:00 en Madrid): ya cuenta como pendiente por la mañana.
        _estado(q2, AHORA + timedelta(hours=6), AHORA - timedelta(days=5), stability=20)
        # Vence mañana: hoy no.
        _estado(q3, AHORA + timedelta(days=1), AHORA - timedelta(days=1), stability=4)
        db.session.commit()

        pendientes, nuevas = daily_review(exam, AHORA)
        assert pendientes == [q1, q2]
        assert len(nuevas) == 3
        assert not {q1, q2, q3} & set(nuevas), "las nuevas tienen que ser preguntas nunca vistas"

        # Una pregunta estrenada hoy gasta cupo de nuevas.
        tanda = StudySession(exam_id=exam.id, mode="repaso", question_count=1)
        db.session.add(tanda)
        db.session.flush()
        db.session.add(Attempt(question_id=q4.id, session_id=tanda.id, selected=[0], is_correct=True,
                               answered_at=AHORA - timedelta(hours=1)))
        _estado(q4, AHORA + timedelta(days=2), AHORA - timedelta(hours=1), stability=2)
        db.session.commit()

        pendientes, nuevas = daily_review(exam, AHORA)
        assert pendientes == [q1, q2]
        assert len(nuevas) == 2
        assert q4 not in nuevas


def test_la_prevision_de_los_proximos_dias(app, examen):
    with app.app_context():
        exam = Exam.query.filter_by(code="AIB-C01").one()
        exam.new_per_day = 0
        preguntas = _preguntas(exam, 5)
        dias = [-3, 0, 1, 1, 3]  # atrasada, hoy, mañana, mañana, dentro de tres días
        for q, d in zip(preguntas, dias):
            _estado(q, AHORA + timedelta(days=d), AHORA - timedelta(days=5), stability=5)
        db.session.commit()

        resumen = review_summary(exam, AHORA)
        assert resumen["due"] == 2 and resumen["new"] == 0 and resumen["total"] == 2
        assert [n for _dia, n in resumen["forecast"]] == [2, 2, 0, 1, 0, 0, 0]
        assert resumen["forecast"][0][0] == AHORA.astimezone(MADRID).date()


def test_sin_nada_pendiente_la_portada_ofrece_una_tanda_rapida(app, logged_in, examen):
    with app.app_context():
        Exam.query.filter_by(code="AIB-C01").one().new_per_day = 0
        db.session.commit()

    html = logged_in.get("/").get_data(as_text=True)
    assert "Repaso de hoy" in html
    assert "Nada pendiente hoy" in html
    assert 'data-mode="rapida"' in html
    assert "Repaso de fallos" not in html

    respuesta = logged_in.post("/api/session/start", json={"mode": "repaso"})
    assert respuesta.status_code == 409
    assert "tanda rápida" in respuesta.get_json()["error"]


def test_el_repaso_sirve_las_nuevas_del_dia(app, logged_in, examen):
    """Sin historial, el repaso de hoy son las nuevas del cupo, sin repetir."""
    html = logged_in.get("/").get_data(as_text=True)
    assert "0 pendientes · 10 nuevas" in html

    inicio = logged_in.post("/api/session/start", json={"mode": "repaso"}).get_json()
    assert inicio["total"] == 10
    vistas = set()
    for _ in range(inicio["total"]):
        logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
    logged_in.post("/api/session/finish")
    with app.app_context():
        vistas = {a.question_id for a in Attempt.query.all()}
    assert len(vistas) == 10

    # Estrenadas hoy las diez, ya no quedan nuevas por hoy.
    assert "10 nuevas" not in logged_in.get("/").get_data(as_text=True)
