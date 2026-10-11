"""Repetición espaciada con FSRS (issue #16)."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fsrs import Card, Rating

from app.extensions import db
from app.models import Attempt, Exam, Question, ReviewState, StudySession
from app.srs import DEFAULT_RATING_CONFIG, cap_due, rating_for, rebuild, review, utc

CONFIG = DEFAULT_RATING_CONFIG
REF = 60  # segundos de referencia: lento > 90, rápido < 30


@pytest.mark.parametrize(
    "correcta, confianza, pista, segundos, nota",
    [
        (False, "sure", False, 40, Rating.Again),
        (False, "unsure", True, 10, Rating.Again),
        (True, "unsure", False, 40, Rating.Hard),
        (True, "sure", True, 40, Rating.Hard),
        (True, "sure", False, 120, Rating.Hard),  # lento
        (True, "sure", False, 40, Rating.Good),
        (True, "sure", False, 10, Rating.Easy),  # rápido
        (True, "unsure", False, 10, Rating.Hard),  # rápido pero con duda: manda la duda
        (True, None, None, 40, Rating.Good),  # intentos anteriores a #13: cuenta como seguro
        (True, "sure", False, None, Rating.Good),  # sin tiempo: ni lento ni rápido
    ],
)
def test_la_nota_que_merece_cada_respuesta(correcta, confianza, pista, segundos, nota):
    assert rating_for(correcta, confianza, pista, segundos, REF, CONFIG) == nota


AHORA = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def _tarjeta(due):
    return Card(card_id=1, due=due)


@pytest.mark.parametrize(
    "fecha_examen, due, esperado",
    [
        # Caería después del examen: se adelanta a la víspera.
        (date(2026, 11, 20), AHORA + timedelta(days=60), datetime(2026, 11, 19, tzinfo=timezone.utc)),
        # Cae antes: no se toca.
        (date(2026, 11, 20), AHORA + timedelta(days=5), AHORA + timedelta(days=5)),
        # El examen es mañana y la víspera ya pasó: lo antes posible, ahora.
        (date(2026, 11, 2), AHORA + timedelta(days=30), AHORA),
        # El examen ya pasó: no hay nada que adelantar.
        (date(2026, 10, 1), AHORA + timedelta(days=30), AHORA + timedelta(days=30)),
        # Sin fecha de examen.
        (None, AHORA + timedelta(days=300), AHORA + timedelta(days=300)),
    ],
)
def test_ningun_repaso_cae_despues_del_examen(fecha_examen, due, esperado):
    examen = SimpleNamespace(exam_date=fecha_examen)
    assert cap_due(_tarjeta(due), examen, AHORA).due == esperado


def test_la_referencia_de_tiempo_tiene_un_minimo(app, monkeypatch):
    """Con respuestas de 0-1 s (pruebas automáticas), la mediana es 0 y todo
    acierto contaría como lento. La referencia nunca baja del mínimo."""
    from app import srs

    class _Consulta:
        def __getattr__(self, _nombre):
            return lambda *a, **k: self

        def all(self):
            return [(0,)] * 30 + [(1,)] * 10

    with app.app_context():
        examen = Exam.query.filter_by(code="AIB-C01").one()
        monkeypatch.setattr(srs.db.session, "query", lambda *a: _Consulta())
        referencia = srs.reference_seconds(examen, CONFIG)
    assert referencia == CONFIG["min_reference_seconds"]
    assert rating_for(True, "sure", False, 1, referencia, CONFIG) == Rating.Easy


def test_utc_normaliza_lo_que_devuelven_sqlite_y_postgres():
    sin_zona = datetime(2026, 1, 1, 12, 0)
    otra_zona = datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1)))
    assert utc(sin_zona).tzinfo is timezone.utc
    assert utc(otra_zona) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert utc(otra_zona).tzinfo is timezone.utc


def _instantanea(app):
    """Estados FSRS y notas de las respuestas, comparables entre sí."""
    with app.app_context():
        estados = {
            s.question_id: (s.state, s.step, s.stability, s.difficulty, utc(s.due), utc(s.last_review))
            for s in ReviewState.query.all()
        }
        notas = {a.id: (a.rating, a.predicted_r) for a in Attempt.query.all()}
        return estados, notas


@pytest.fixture
def sin_progreso(app):
    yield
    app.test_cli_runner().invoke(args=["db-reset-progress", "--yes"])


def test_responder_actualiza_el_estado_de_la_pregunta(app, logged_in, sin_progreso):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    respuesta = logged_in.post("/api/session/answer", json={"selected": [0], "seconds_spent": 30, "confidence": "sure"})
    assert respuesta.status_code == 200

    with app.app_context():
        intento = Attempt.query.filter_by(session_id=inicio["study_session_id"]).one()
        estado = ReviewState.query.filter_by(question_id=intento.question_id).one()
        assert intento.rating in (int(Rating.Again), int(Rating.Good), int(Rating.Easy))
        assert intento.predicted_r is None, "una pregunta nunca vista no tiene predicción que medir"
        assert utc(estado.last_review) == utc(intento.answered_at)
        assert utc(estado.due) > utc(intento.answered_at)

        # Una segunda respuesta días después sí tiene predicción, entre 0 y 1.
        pregunta = db.session.get(Question, intento.question_id)
        mas_tarde = utc(intento.answered_at) + timedelta(days=3)
        segundo = Attempt(question_id=pregunta.id, session_id=intento.session_id, selected=list(pregunta.correct),
                          is_correct=True, seconds_spent=40, confidence="sure", answered_at=mas_tarde)
        review(segundo, pregunta, pregunta.exam, now=mas_tarde)
        assert 0 < segundo.predicted_r < 1
        assert segundo.rating == int(Rating.Good)
        db.session.rollback()


def test_rebuild_es_idempotente(app, sin_progreso):
    resultado = app.test_cli_runner().invoke(args=["db-seed-demo", "--reset"])
    assert resultado.exit_code == 0, resultado.output
    antes = _instantanea(app)
    assert antes[0], "la demostración debería dejar estados FSRS"
    assert all(nota is not None for nota, _r in antes[1].values())

    resultado = app.test_cli_runner().invoke(args=["fsrs", "rebuild"])
    assert resultado.exit_code == 0, resultado.output
    assert _instantanea(app) == antes


def test_reconstruir_da_lo_mismo_que_ir_respondiendo(app, logged_in, sin_progreso):
    """El estado que deja /answer y el que deja rebuild desde cero son el mismo."""
    for _ in range(2):
        logged_in.post("/api/session/start", json={"mode": "rapida"})
        for segundos, confianza in ((20, "sure"), (95, "sure"), (40, "unsure")):
            logged_in.post("/api/session/answer",
                           json={"selected": [0], "seconds_spent": segundos, "confidence": confianza})
        logged_in.post("/api/session/finish")
    al_responder = _instantanea(app)

    with app.app_context():
        ReviewState.query.delete()
        db.session.commit()
        rebuild()
    assert _instantanea(app) == al_responder


def test_borrar_el_progreso_borra_el_estado_fsrs(app, logged_in):
    logged_in.post("/api/session/start", json={"mode": "rapida"})
    logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
    with app.app_context():
        assert ReviewState.query.count() > 0
    app.test_cli_runner().invoke(args=["db-reset-progress", "--yes"])
    with app.app_context():
        assert ReviewState.query.count() == 0


def test_la_retencion_deseada_sale_del_examen(app):
    from app.srs import active_parameters, scheduler_for

    with app.app_context():
        examen = Exam.query.filter_by(code="AIB-C01").one()
        assert scheduler_for(examen, active_parameters(examen)).desired_retention == examen.desired_retention
        db.session.rollback()
