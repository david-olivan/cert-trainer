"""Señales que se guardan con cada respuesta (issue #13).

Confianza, pista usada y orden de opciones mostrado. Son la materia prima
de la repetición espaciada y de sus métricas: si dejan de guardarse, nada
falla a la vista, pero el historial que se acumula ya no sirve para
ajustar el algoritmo.
"""
import pytest

from app.extensions import db
from app.models import Attempt, StudySession


@pytest.fixture
def tanda(app, logged_in):
    """Arranca una tanda rápida y la borra al terminar la prueba."""
    respuesta = logged_in.post("/api/session/start", json={"mode": "rapida"})
    assert respuesta.status_code == 200, respuesta.data
    cuerpo = respuesta.get_json()
    yield cuerpo
    with app.app_context():
        Attempt.query.filter_by(session_id=cuerpo["study_session_id"]).delete()
        db.session.delete(db.session.get(StudySession, cuerpo["study_session_id"]))
        db.session.commit()


def _ultimo_intento(app, study_session_id):
    with app.app_context():
        intento = (
            Attempt.query.filter_by(session_id=study_session_id)
            .order_by(Attempt.id.desc())
            .first()
        )
        db.session.expunge(intento)
        return intento


def test_se_guardan_confianza_pista_y_orden(app, logged_in, tanda):
    n_opciones = len(tanda["question"]["options"])
    respuesta = logged_in.post(
        "/api/session/answer",
        json={"selected": [1], "seconds_spent": 40, "confidence": "unsure", "hint_used": True},
    )
    assert respuesta.status_code == 200, respuesta.data

    intento = _ultimo_intento(app, tanda["study_session_id"])
    assert intento.confidence == "unsure"
    assert intento.hint_used is True
    assert sorted(intento.option_order) == list(range(n_opciones)), "debe ser una permutación"
    # `selected` se guarda en índices originales: la opción mostrada en la
    # posición 1 es la original option_order[1].
    assert intento.selected == [intento.option_order[1]]


def test_sin_senales_se_guardan_como_desconocidas(app, logged_in, tanda):
    """Una pestaña con el JavaScript anterior no manda las señales.

    Se guardan nulas, no con un valor supuesto, y el orden de opciones se
    guarda igual porque lo conoce el servidor.
    """
    respuesta = logged_in.post("/api/session/answer", json={"selected": [0], "seconds_spent": 20})
    assert respuesta.status_code == 200, respuesta.data

    intento = _ultimo_intento(app, tanda["study_session_id"])
    assert intento.confidence is None
    assert intento.hint_used is None
    assert intento.option_order is not None


@pytest.mark.parametrize(
    "senales",
    [{"confidence": "quizas"}, {"hint_used": "si"}],
)
def test_una_senal_mal_formada_se_rechaza_sin_guardar(app, logged_in, tanda, senales):
    respuesta = logged_in.post("/api/session/answer", json={"selected": [0], **senales})
    assert respuesta.status_code == 400
    assert respuesta.get_json()["error"]

    with app.app_context():
        assert Attempt.query.filter_by(session_id=tanda["study_session_id"]).count() == 0


def test_la_demostracion_genera_senales(app):
    """db-seed-demo tiene que dejar señales variadas para poder revisar las métricas."""
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["db-seed-demo", "--reset"])
    assert resultado.exit_code == 0, resultado.output
    try:
        with app.app_context():
            intentos = Attempt.query.all()
            assert intentos
            assert all(i.confidence in ("sure", "unsure") for i in intentos)
            assert all(i.option_order is not None for i in intentos)
            assert any(i.confidence == "unsure" for i in intentos)
            assert any(not i.is_correct and i.confidence == "sure" for i in intentos), (
                "faltan fallos marcados como «seguro», que son los errores de concepto"
            )
            assert any(i.hint_used for i in intentos)
    finally:
        runner.invoke(args=["db-reset-progress", "--yes"])
