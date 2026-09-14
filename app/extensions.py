"""Instancias compartidas de las extensiones Flask.

Separadas de __init__.py para evitar import circular: los blueprints
importan `db`/`login_manager` de aquí, no de la factory.
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = None  # el propio formulario ya deja claro que hace falta iniciar sesión
