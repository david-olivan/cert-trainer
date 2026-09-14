"""Acceso de un único usuario. Ver SPEC.md 1.1."""
import time

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from app.models import User

bp = Blueprint("auth", __name__)

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60

# Contador de intentos fallidos por IP, en memoria. Un solo usuario y un
# proceso gunicorn de 2 workers en el peor caso: suficiente sin añadir una
# dependencia nueva (Flask-Limiter) ni una tabla en BD para esto.
_failed_attempts: dict[str, list[float]] = {}


def _client_key():
    return request.remote_addr or "desconocido"


def _is_locked_out(key):
    now = time.time()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < LOCKOUT_SECONDS]
    _failed_attempts[key] = attempts
    return len(attempts) >= MAX_ATTEMPTS


def _register_failure(key):
    _failed_attempts.setdefault(key, []).append(time.time())


def _clear_failures(key):
    _failed_attempts.pop(key, None)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("practice.home"))

    error = None
    if request.method == "POST":
        key = _client_key()
        if _is_locked_out(key):
            error = (
                f"Demasiados intentos fallidos. Espera {LOCKOUT_SECONDS // 60} minutos "
                "antes de volver a intentarlo."
            )
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                _clear_failures(key)
                login_user(user, remember=True)
                return redirect(url_for("practice.home"))
            _register_failure(key)
            error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
