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
