from flask import Flask, Response

from app.config import Config
from app.extensions import db, login_manager, migrate


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config())

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
