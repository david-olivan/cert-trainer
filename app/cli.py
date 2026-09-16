"""Comandos de consola: `flask questions import/export`, `flask db-seed`,
`flask db-seed-demo` y `flask db-reset-progress`."""
import json
import random
from datetime import timedelta

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.import_validation import question_to_short_format, validate_import
from app.models import Attempt, Question, StudySession, User, utcnow
from app.progress import reset_progress
from app.sampling import DOMAIN_WEIGHTS, weighted_sample


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


# Perfil de la demostración: cada dominio con una preparación distinta a
# propósito, para que el medidor de inicio muestre los cuatro estados que
# sabe pintar (por debajo de 60, entre 60 y el umbral, y por encima).
DEMO_ACCURACY = {1: 0.86, 2: 0.54, 3: 0.71, 4: 0.64}

# (modo, número de preguntas, días atrás). Mezcla de los cuatro modos para
# que el historial de inicio no sea una lista de tandas idénticas.
DEMO_SESSIONS = [
    ("rapida", 10, 18),
    ("dominio", 11, 15),
    ("simulacro", 20, 12),
    ("rapida", 10, 8),
    ("fallos", 12, 5),
    ("rapida", 10, 2),
]


def _demo_selected(question, is_correct, rng):
    """Índices que habría marcado el usuario para acertar o fallar la pregunta."""
    correct = list(question.correct)
    if is_correct:
        return sorted(correct)

    wrong_pool = [i for i in range(len(question.options)) if i not in correct]
    if not wrong_pool:
        return []
    if question.type == "m" and len(correct) > 1:
        # Fallo típico de respuesta múltiple: una acertada y una de más.
        return sorted([correct[0], rng.choice(wrong_pool)])
    return [rng.choice(wrong_pool)]


def _demo_seconds(is_correct, rng):
    """Tiempo por pregunta plausible. Incluye aciertos lentos a propósito:
    son la señal que explota la fase 2.2 y deben verse en los diseños."""
    if not is_correct:
        return rng.randint(45, 150)
    if rng.random() < 0.2:
        return rng.randint(95, 165)  # acertada tras mucha duda
    return rng.randint(20, 70)


@click.command("db-seed-demo")
@click.option("--reset", is_flag=True, help="Borra el progreso existente antes de generar la demostración.")
@with_appcontext
def db_seed_demo(reset):
    """Genera sesiones e intentos sintéticos para revisar la interfaz con datos.

    No toca el banco de preguntas: solo escribe en `study_sessions` y
    `attempts`. Pensado para desarrollo, no para producción.
    """
    if Question.query.filter_by(active=True).first() is None:
        click.echo(
            "El banco de preguntas está vacío. Ejecuta primero `flask db-seed` "
            "para sembrarlo y vuelve a intentarlo."
        )
        return

    if reset:
        removed = reset_progress()
        click.echo(f"Progreso anterior borrado: {removed['sessions']} sesiones, {removed['attempts']} intentos.")
    elif StudySession.query.first() is not None:
        click.echo(
            "Ya hay progreso registrado. Vuelve a ejecutarlo con --reset si "
            "quieres sustituirlo por la demostración."
        )
        return

    # Semilla fija: la demostración es reproducible, de modo que dos
    # capturas de pantalla de la misma pantalla se pueden comparar. Se
    # siembra también el `random` global porque es el que usa
    # app.sampling.weighted_sample para elegir las preguntas de cada tanda.
    rng = random.Random(20260915)
    random.seed(20260915)
    now = utcnow()
    total_attempts = 0

    for mode, count, days_ago in DEMO_SESSIONS:
        domain = rng.choice(sorted(DOMAIN_WEIGHTS)) if mode == "dominio" else None
        if domain is not None:
            pool = Question.query.filter_by(active=True, domain=domain).all()
            rng.shuffle(pool)
            questions = pool[:count]
        else:
            questions = weighted_sample(count)
        if not questions:
            continue

        started_at = now - timedelta(days=days_ago, hours=rng.randint(0, 10))
        study_session = StudySession(
            mode=mode,
            domain=domain,
            started_at=started_at,
            question_count=len(questions),
        )
        db.session.add(study_session)
        db.session.flush()  # necesitamos el id para los intentos

        answered_at = started_at
        correct_count = 0
        for question in questions:
            is_correct = rng.random() < DEMO_ACCURACY[question.domain]
            seconds = _demo_seconds(is_correct, rng)
            answered_at = answered_at + timedelta(seconds=seconds)
            db.session.add(
                Attempt(
                    question_id=question.id,
                    session_id=study_session.id,
                    selected=_demo_selected(question, is_correct, rng),
                    is_correct=is_correct,
                    seconds_spent=seconds,
                    answered_at=answered_at,
                )
            )
            correct_count += 1 if is_correct else 0
            total_attempts += 1

        study_session.finished_at = answered_at
        study_session.score_pct = round(correct_count / len(questions) * 100)

    db.session.commit()
    click.echo(
        f"Demostración generada: {len(DEMO_SESSIONS)} sesiones y {total_attempts} "
        "intentos sintéticos. Bórralos con `flask db-reset-progress`."
    )


@click.command("db-reset-progress")
@click.option("--yes", is_flag=True, help="No pedir confirmación.")
@with_appcontext
def db_reset_progress(yes):
    """Borra todo el progreso (sesiones e intentos). El banco no se toca."""
    sessions = StudySession.query.count()
    attempts = Attempt.query.count()
    if not sessions and not attempts:
        click.echo("No hay progreso que borrar.")
        return

    if not yes:
        click.confirm(
            f"Se van a borrar {sessions} sesiones y {attempts} intentos. "
            "Las preguntas no se tocan. ¿Continuar?",
            abort=True,
        )

    removed = reset_progress()
    click.echo(f"Borrados {removed['sessions']} sesiones y {removed['attempts']} intentos.")


def register_cli(app):
    app.cli.add_command(questions_cli)
    app.cli.add_command(db_seed)
    app.cli.add_command(db_seed_demo)
    app.cli.add_command(db_reset_progress)
