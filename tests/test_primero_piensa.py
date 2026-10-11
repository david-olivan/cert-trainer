"""Modo «primero piensa»: el enunciado antes que las opciones (issue #14).

La preferencia vive en el servidor y es el servidor quien decide, al
empezar cada tanda, si el modo se aplica. Lo que se guarda en cada
respuesta permite comparar después el acierto con el modo y sin él.
"""
import pytest

from app.extensions import db
from app.models import Attempt, StudySession, User


def _recall_first_del_usuario(app):
    with app.app_context():
        return User.query.one().recall_first


@pytest.fixture
def modo_activo(app, logged_in):
    """Enciende el modo para la prueba y lo deja apagado al terminar."""
    respuesta = logged_in.post("/preferencias/primero-piensa")
    assert respuesta.status_code == 302
    assert _recall_first_del_usuario(app) is True
    yield
    with app.app_context():
        User.query.one().recall_first = False
        db.session.commit()


def _borrar_tanda(app, study_session_id):
    with app.app_context():
        Attempt.query.filter_by(session_id=study_session_id).delete()
        db.session.delete(db.session.get(StudySession, study_session_id))
        db.session.commit()


def _ultimo_intento(app, study_session_id):
    with app.app_context():
        intento = Attempt.query.filter_by(session_id=study_session_id).one()
        db.session.expunge(intento)
        return intento


def test_por_defecto_esta_apagado(app):
    assert _recall_first_del_usuario(app) is False


def test_el_interruptor_alterna_y_la_portada_lo_refleja(app, logged_in):
    try:
        logged_in.post("/preferencias/primero-piensa")
        assert _recall_first_del_usuario(app) is True
        assert b'aria-checked="true"' in logged_in.get("/").data

        logged_in.post("/preferencias/primero-piensa")
        assert _recall_first_del_usuario(app) is False
        assert b'aria-checked="false"' in logged_in.get("/").data
    finally:
        with app.app_context():
            User.query.one().recall_first = False
            db.session.commit()


def test_con_el_modo_activo_se_guarda_el_tiempo_hasta_ver_opciones(app, logged_in, modo_activo):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    try:
        assert inicio["recall_first"] is True
        respuesta = logged_in.post(
            "/api/session/answer",
            json={"selected": [0], "seconds_spent": 50, "confidence": "sure", "seconds_to_reveal": 18},
        )
        assert respuesta.status_code == 200, respuesta.data

        intento = _ultimo_intento(app, inicio["study_session_id"])
        assert intento.recall_first is True
        assert intento.seconds_to_reveal == 18
    finally:
        _borrar_tanda(app, inicio["study_session_id"])


def test_en_simulacro_no_se_aplica(app, logged_in, modo_activo):
    inicio = logged_in.post("/api/session/start", json={"mode": "simulacro"}).get_json()
    try:
        assert inicio["recall_first"] is False
        # Aunque el cliente mandase un tiempo, sin el modo no se guarda.
        logged_in.post(
            "/api/session/answer",
            json={"selected": [0], "confidence": "sure", "seconds_to_reveal": 7},
        )
        intento = _ultimo_intento(app, inicio["study_session_id"])
        assert intento.recall_first is False
        assert intento.seconds_to_reveal is None
    finally:
        _borrar_tanda(app, inicio["study_session_id"])


def test_con_el_modo_apagado_se_guarda_que_no_se_uso(app, logged_in):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    try:
        assert inicio["recall_first"] is False
        logged_in.post("/api/session/answer", json={"selected": [0], "confidence": "sure"})
        intento = _ultimo_intento(app, inicio["study_session_id"])
        assert intento.recall_first is False
        assert intento.seconds_to_reveal is None
    finally:
        _borrar_tanda(app, inicio["study_session_id"])


@pytest.mark.parametrize("valor", [-3, "12", 4.5, True])
def test_un_tiempo_mal_formado_se_rechaza(app, logged_in, modo_activo, valor):
    inicio = logged_in.post("/api/session/start", json={"mode": "rapida"}).get_json()
    try:
        respuesta = logged_in.post(
            "/api/session/answer",
            json={"selected": [0], "confidence": "sure", "seconds_to_reveal": valor},
        )
        assert respuesta.status_code == 400
        with app.app_context():
            assert Attempt.query.filter_by(session_id=inicio["study_session_id"]).count() == 0
    finally:
        _borrar_tanda(app, inicio["study_session_id"])


def test_la_demostracion_mezcla_tandas_con_y_sin_el_modo(app):
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["db-seed-demo", "--reset"])
    assert resultado.exit_code == 0, resultado.output
    try:
        with app.app_context():
            intentos = Attempt.query.join(StudySession).all()
            con_modo = [i for i in intentos if i.recall_first]
            assert con_modo, "ninguna tanda de la demostración usa «primero piensa»"
            assert any(i.recall_first is False for i in intentos)
            assert all(i.session.mode != "simulacro" for i in con_modo)
            assert all(0 < i.seconds_to_reveal < i.seconds_spent for i in con_modo)
    finally:
        runner.invoke(args=["db-reset-progress", "--yes"])
