"""Fixtures de la batería de humo.

Se monta la aplicación igual que en producción: variables de entorno
obligatorias, migraciones de Alembic (no `create_all`, que no probaría
nada del camino real de despliegue) y siembra por el mismo comando que
lanza `docker-start.sh`.
"""
import os

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "contraseña-de-prueba"


@pytest.fixture(scope="session")
def database_url(tmp_path_factory):
    """La de CI si existe (Postgres real), si no un sqlite desechable.

    En CI no se admite el sqlite: si TEST_DATABASE_URL no llega, la tanda
    se cae en vez de pasar contra un motor que no es el de producción. Ese
    silencio es justo lo que dejó colarse el SELECT DISTINCT sobre
    columnas json, que sqlite acepta y Postgres no.
    """
    configured = os.environ.get("TEST_DATABASE_URL")
    if configured:
        return configured
    if os.environ.get("CI"):
        raise RuntimeError(
            "Falta TEST_DATABASE_URL en CI. Las pruebas tienen que correr "
            "contra Postgres, como producción: pasar contra sqlite no "
            "demuestra que el despliegue funcione. Revisa el servicio "
            "postgres del workflow."
        )
    return "sqlite:///" + str(tmp_path_factory.mktemp("db") / "test.db")


@pytest.fixture(scope="session")
def app(database_url):
    os.environ["SECRET_KEY"] = "clave-de-prueba"
    os.environ["ADMIN_PASSWORD_HASH"] = generate_password_hash(PASSWORD)
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["DATABASE_URL"] = database_url
    os.environ["FORCE_HTTPS"] = "false"

    from app import create_app

    application = create_app()
    application.config["TESTING"] = True

    with application.app_context():
        from flask_migrate import upgrade

        upgrade()
        application.test_cli_runner().invoke(args=["db-seed"])

    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302, "el acceso con credenciales buenas debería redirigir"
    return client
