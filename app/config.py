"""Configuración desde variables de entorno.

Regla de CLAUDE.md/SPEC.md: si falta SECRET_KEY la aplicación no arranca.
No se genera una clave aleatoria en silencio.
"""
import os

# Raíz del proyecto (un nivel por encima de app/), para resolver rutas
# sqlite relativas nosotros mismos: Flask-SQLAlchemy resuelve
# "sqlite:///data/app.db" contra app.instance_path (p. ej.
# /app/instance/data/app.db dentro del contenedor), no contra el
# directorio de trabajo, y esa carpeta no existe ni se monta en
# docker-compose.yml. Anclarlo aquí evita el "unable to open database
# file" y mantiene coherencia entre `flask run` local y Docker.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_sqlite_url(database_url: str) -> str:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and not database_url.startswith("sqlite:////"):
        relative_path = database_url[len(prefix):]
        absolute_path = os.path.join(PROJECT_ROOT, relative_path)
        return "sqlite:///" + absolute_path.replace(os.sep, "/")
    return database_url


def _resolve_postgres_url(database_url: str) -> str:
    """Fuerza el driver psycopg (v3), el único que instalamos.

    Neon (y casi cualquier proveedor gestionado) entrega la cadena como
    "postgresql://usuario:clave@host/base?sslmode=require". SQLAlchemy
    resuelve ese esquema sin driver a psycopg2, que no está en
    requirements.txt, y la aplicacion muere al arrancar con
    ModuleNotFoundError antes de servir una sola petición. Reescribimos el
    esquema aquí para poder pegar la cadena del proveedor tal cual en la
    variable de entorno, sin editarla a mano en cada rotación.
    """
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url[len(prefix):]
    return database_url


def _engine_options(database_uri: str) -> dict:
    """Opciones de pool. Sin esto, cada sesión de estudio empieza con un error.

    La base de Neon se autosuspende a los pocos minutos de inactividad y el
    servicio gratuito de Render se duerme a los quince: cuando se vuelve a
    abrir la aplicación, las conexiones que quedaron en el pool están
    muertas y la primera petición falla. pool_pre_ping las descarta antes
    de usarlas y pool_recycle no deja envejecer ninguna mas de cinco
    minutos. En sqlite no aplica: no hay red de por medio.
    """
    if database_uri.startswith("sqlite:"):
        return {}
    return {"pool_pre_ping": True, "pool_recycle": 300}


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"Falta la variable de entorno {name}. Copia .env.example a .env "
            f"y rellénala antes de arrancar la aplicación."
        )
    return value


class Config:
    def __init__(self):
        self.SECRET_KEY = _require("SECRET_KEY")
        self.ADMIN_PASSWORD_HASH = _require("ADMIN_PASSWORD_HASH")
        self.ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")

        database_url = os.environ.get("DATABASE_URL", "sqlite:///data/app.db")
        database_url = _resolve_postgres_url(database_url)
        self.SQLALCHEMY_DATABASE_URI = _resolve_sqlite_url(database_url)
        self.SQLALCHEMY_ENGINE_OPTIONS = _engine_options(self.SQLALCHEMY_DATABASE_URI)
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        self.FORCE_HTTPS = os.environ.get("FORCE_HTTPS", "false").lower() == "true"

        # Cookies de sesión: HttpOnly y SameSite=Lax siempre; Secure solo si
        # hay HTTPS por delante (en local con FORCE_HTTPS=false rompería el login).
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = self.FORCE_HTTPS
        self.REMEMBER_COOKIE_HTTPONLY = True
        self.REMEMBER_COOKIE_SAMESITE = "Lax"
        self.REMEMBER_COOKIE_SECURE = self.FORCE_HTTPS

        # "Recordar sesión" con caducidad larga: uso diario desde los mismos
        # dos dispositivos, según CLAUDE.md.
        self.REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 30  # 30 días
        self.PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30

        self.MINUTES_PER_QUESTION = 2
