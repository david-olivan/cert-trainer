"""Que la aplicación desplegada arranca, deja entrar y no se indexa.

Es el mínimo que tiene que pasar antes de que un commit llegue a Render.
"""


def test_healthz_responde_sin_tocar_la_base(client):
    respuesta = client.get("/healthz")
    assert respuesta.status_code == 200
    assert b"ok" in respuesta.data


def test_sin_sesion_la_portada_redirige_al_acceso(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_sin_sesion_la_importacion_redirige_al_acceso(client):
    respuesta = client.get("/preguntas/")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_la_pantalla_de_acceso_se_pinta(client):
    respuesta = client.get("/login")
    assert respuesta.status_code == 200
    assert b"<form" in respuesta.data


def test_una_contrasena_mala_no_entra(client):
    respuesta = client.post(
        "/login", data={"username": "admin", "password": "esto-no-es"}
    )
    assert respuesta.status_code == 200
    assert "incorrectos".encode() in respuesta.data


def test_con_sesion_la_portada_se_pinta(logged_in):
    respuesta = logged_in.get("/")
    assert respuesta.status_code == 200


def test_el_banco_se_sembro(app):
    """Si esto falla en producción, se entra pero no hay nada que estudiar."""
    with app.app_context():
        from app.models import Question, User

        assert Question.query.count() > 0
        assert User.query.count() == 1


def test_se_puede_empezar_una_tanda(logged_in):
    respuesta = logged_in.post("/api/session/start", json={"mode": "rapida"})
    assert respuesta.status_code == 200, respuesta.data
    cuerpo = respuesta.get_json()
    assert cuerpo["total"] > 0
    assert "correct" not in cuerpo["question"], "la respuesta correcta no puede viajar al cliente"


def test_no_se_indexa(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert b"Disallow: /" in robots.data
    assert "noindex" in robots.headers["X-Robots-Tag"]


def test_la_portada_cuenta_los_fallos(app, logged_in):
    """El recuento de fallos de la portada, con un fallo de verdad en la base.

    Esta consulta hacía un SELECT DISTINCT sobre la entidad Question, que
    arrastra columnas json; Postgres no sabe compararlas por igualdad y
    devolvía 500 mientras en sqlite pasaba. Va con datos porque un
    recuento a cero puede salir bien por accidente.
    """
    from app.extensions import db
    from app.models import Attempt, Question, StudySession

    with app.app_context():
        pregunta = Question.query.filter_by(active=True).first()
        tanda = StudySession(mode="rapida", question_count=1)
        db.session.add(tanda)
        db.session.commit()
        db.session.add(
            Attempt(
                question_id=pregunta.id,
                session_id=tanda.id,
                selected=[0],
                is_correct=False,
                seconds_spent=30,
            )
        )
        db.session.commit()
        attempt_id = Attempt.query.order_by(Attempt.id.desc()).first().id
        tanda_id = tanda.id

    try:
        respuesta = logged_in.get("/")
        assert respuesta.status_code == 200, respuesta.data[:400]
        # La pregunta fallada tiene que aparecer contada como repasable.
        assert b"1" in respuesta.data
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Attempt, attempt_id))
            db.session.delete(db.session.get(StudySession, tanda_id))
            db.session.commit()
