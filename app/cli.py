"""Comandos de consola: `flask questions import/export`, `flask db-seed`."""
import json

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.import_validation import question_to_short_format, validate_import
from app.models import Question, User


@click.group("questions")
def questions_cli():
    """Importar o exportar el banco de preguntas."""


@questions_cli.command("import")
@click.argument("fichero", type=click.Path(exists=True, dir_okay=False))
@with_appcontext
def import_questions(fichero):
    """Valida e inserta las preguntas de FICHERO (mismo validador que la web)."""
    with open(fichero, encoding="utf-8") as f:
        items = json.load(f)

    result = validate_import(items)
    for item in result.accepted:
        db.session.add(Question(**item))
    db.session.commit()

    click.echo(f"Insertadas {len(result.accepted)} preguntas.")
    if result.rejected:
        click.echo(f"Descartadas {len(result.rejected)}:")
        for identifier, reason in result.rejected:
            click.echo(f"  - {identifier}: {reason}")


@questions_cli.command("export")
@click.argument("fichero", type=click.Path(dir_okay=False))
@with_appcontext
def export_questions(fichero):
    """Vuelca el banco completo (preguntas activas) a FICHERO en formato corto."""
    questions = Question.query.filter_by(active=True).order_by(Question.ext_id).all()
    data = [question_to_short_format(q) for q in questions]
    with open(fichero, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    click.echo(f"Exportadas {len(data)} preguntas a {fichero}.")


def _ensure_admin_user():
    """Siembra la fila única de User desde ADMIN_USERNAME/ADMIN_PASSWORD_HASH."""
    username = current_app.config["ADMIN_USERNAME"]
    existing = User.query.filter_by(username=username).first()
    if existing is not None:
        # Si el hash cambió en el entorno (rotación de contraseña), lo actualizamos.
        if existing.password_hash != current_app.config["ADMIN_PASSWORD_HASH"]:
            existing.password_hash = current_app.config["ADMIN_PASSWORD_HASH"]
            db.session.commit()
            click.echo(f"Contraseña de {username} actualizada desde el entorno.")
        return
    db.session.add(User(username=username, password_hash=current_app.config["ADMIN_PASSWORD_HASH"]))
    db.session.commit()
    click.echo(f"Usuario {username} creado.")


@click.command("db-seed")
@with_appcontext
def db_seed():
    """Siembra el usuario único y el banco desde data/questions.seed.json."""
    _ensure_admin_user()

    if Question.query.first() is not None:
        click.echo("La tabla de preguntas ya tiene datos; no se siembra de nuevo.")
        return

    seed_path = current_app.config.get("SEED_QUESTIONS_PATH", "data/questions.seed.json")
    try:
        with open(seed_path, encoding="utf-8") as f:
            items = json.load(f)
    except FileNotFoundError:
        click.echo(f"No se encontró {seed_path}; no se ha sembrado nada.")
        return

    result = validate_import(items, existing_ext_ids=set())
    for item in result.accepted:
        item["source"] = "seed"
        db.session.add(Question(**item))
    db.session.commit()

    click.echo(f"Sembradas {len(result.accepted)} preguntas desde {seed_path}.")
    if result.rejected:
        click.echo(f"Descartadas {len(result.rejected)} del seed (revisar formato):")
        for identifier, reason in result.rejected:
            click.echo(f"  - {identifier}: {reason}")


def register_cli(app):
    app.cli.add_command(questions_cli)
    app.cli.add_command(db_seed)
