"""Lo que rompe el despliegue antes de servir una sola petición."""
import pytest

from app.config import ConfigError, Config, _engine_options, _resolve_postgres_url


@pytest.mark.parametrize(
    "entrada",
    [
        "postgresql://u:c@ep-uno.neon.tech/neondb?sslmode=require",
        "postgres://u:c@ep-uno.neon.tech/neondb?sslmode=require",
    ],
)
def test_la_cadena_de_neon_usa_psycopg3(entrada):
    """Pegada tal cual, SQLAlchemy la resolvería a psycopg2, que no instalamos."""
    resuelta = _resolve_postgres_url(entrada)
    assert resuelta.startswith("postgresql+psycopg://")

    from sqlalchemy.engine.url import make_url

    assert make_url(resuelta).get_dialect().driver == "psycopg"


def test_se_conserva_el_resto_de_la_cadena():
    resuelta = _resolve_postgres_url("postgresql://u:c@host/base?sslmode=require")
    assert resuelta == "postgresql+psycopg://u:c@host/base?sslmode=require"


def test_no_se_toca_lo_que_ya_trae_driver():
    ya_explicita = "postgresql+psycopg://u:c@host/base"
    assert _resolve_postgres_url(ya_explicita) == ya_explicita


def test_postgres_reutiliza_conexiones_con_cuidado():
    """Neon se autosuspende: sin pre_ping la primera petición del día falla."""
    opciones = _engine_options("postgresql+psycopg://u:c@host/base")
    assert opciones["pool_pre_ping"] is True
    assert opciones["pool_recycle"] == 300


def test_sqlite_no_lleva_opciones_de_pool():
    assert _engine_options("sqlite:///data/app.db") == {}


def test_sin_secret_key_no_arranca(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "x")
    with pytest.raises(ConfigError) as excinfo:
        Config()
    assert "SECRET_KEY" in str(excinfo.value)
