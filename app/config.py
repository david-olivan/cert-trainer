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
        self.SQLALCHEMY_DATABASE_URI = _resolve_sqlite_url(database_url)
        self.SQLALCHEMY_ENGINE_OPTIONS = {}
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
