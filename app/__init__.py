from flask import Flask, Response
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.extensions import db, login_manager, migrate


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config())

    if app.config["FORCE_HTTPS"]:
        # Detrás del proxy de Render, request.remote_addr es la IP del
        # proxy, no la del visitante: sin esto el bloqueo por intentos
        # fallidos de app/auth.py cuenta a todo internet bajo una sola
        # clave y cualquiera que pruebe contraseñas en /login deja al
        # dueño fuera cinco minutos. ProxyFix lee X-Forwarded-For y
        # X-Forwarded-Proto para que la IP y el esquema sean los reales.
        # Solo se activa con FORCE_HTTPS: en local no hay proxy delante y
        # confiar en esas cabeceras permitiría falsificar la IP a mano.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.api import bp as api_bp
    from app.auth import bp as auth_bp
    from app.practice import bp as practice_bp
    from app.questions_admin import bp as questions_admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(practice_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(questions_admin_bp)

    from app.cli import register_cli

    register_cli(app)

    @app.route("/healthz")
    def healthz():
        """Sonda para Render. No toca la base a propósito: debe decir si el
        proceso web está vivo, no si Neon ha despertado, o un autosuspend
        de la base provocaría un reinicio del servicio sin motivo."""
        return Response("ok\n", mimetype="text/plain")

    @app.route("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")

    @app.after_request
    def add_noindex_header(response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    if app.config["FORCE_HTTPS"]:
        from flask import redirect, request

        @app.before_request
        def force_https():
            if request.headers.get("X-Forwarded-Proto", "https") == "http":
                return redirect(request.url.replace("http://", "https://", 1), code=301)

    return app
