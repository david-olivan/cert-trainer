"""Comandos de consola: `flask questions import/export`, `flask db-seed`,
`flask db-seed-demo`, `flask db-reset-progress` y `flask fsrs rebuild/replay`."""
import json
import random
from datetime import timedelta

import click
from flask import current_app
from flask.cli import with_appcontext

from app.exams import current_exam
from app.evaluation import ReplayConfigError, load_parameters, replay
from app.extensions import db
from app.import_validation import ImportPayloadError, question_to_short_format, resolve_payload, validate_import
from app.models import Attempt, Domain, Exam, Question, ReviewState, StudySession, User, utcnow
from app.progress import reset_progress
from app.sampling import weighted_sample
from app.srs import rebuild as rebuild_review_states


@click.group("questions")
def questions_cli():
    """Importar o exportar el banco de preguntas."""


@questions_cli.command("import")
@click.argument("fichero", type=click.Path(exists=True, dir_okay=False))
@with_appcontext
def import_questions(fichero):
    """Valida e inserta las preguntas de FICHERO (mismo validador que la web).

    FICHERO puede ser el array de preguntas (van al examen activo) o
    {"exam": "<código>", "questions": [...]}.
    """
    with open(fichero, encoding="utf-8") as f:
        data = json.load(f)
    try:
        exam, items = resolve_payload(data)
    except ImportPayloadError as exc:
        raise click.ClickException(str(exc))

    result = validate_import(items, exam=exam)
    for item in result.accepted:
        db.session.add(Question(**item))
    db.session.commit()

    click.echo(f"Insertadas {len(result.accepted)} preguntas en {exam.code}.")
    if result.rejected:
        click.echo(f"Descartadas {len(result.rejected)}:")
        for identifier, reason in result.rejected:
            click.echo(f"  - {identifier}: {reason}")


@questions_cli.command("export")
@click.argument("fichero", type=click.Path(dir_okay=False))
@with_appcontext
def export_questions(fichero):
    """Vuelca las preguntas activas del examen en curso a FICHERO en formato corto.

    El formato corto todavía no dice a qué examen pertenece cada pregunta
    (llega con el kit, #20): mientras tanto se exporta solo el examen en curso.
    """
    questions = (
        Question.query.filter_by(active=True, exam_id=current_exam().id).order_by(Question.ext_id).all()
    )
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
DEMO_ACCURACY_DEFAULT = 0.7  # dominios de otros exámenes, más allá del 4

# (modo, número de preguntas, días atrás). Mezcla de los cuatro modos para
# que el historial de inicio no sea una lista de tandas idénticas.
DEMO_SESSIONS = [
    ("rapida", 10, 18),
    ("dominio", 11, 15),
    ("simulacro", 20, 12),
    ("rapida", 10, 8),
    ("repaso", 12, 5),
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


def _demo_signals(question, is_correct, seconds, rng):
    """Confianza, pista y orden de opciones plausibles para un intento.

    Los aciertos lentos y los fallos se marcan más a menudo como «dudo»,
    pero no siempre: los fallos con «seguro» (errores de concepto) son lo
    que más interesa ver en las métricas, así que tienen que aparecer.
    """
    if not is_correct:
        unsure_rate = 0.6
    elif seconds >= 95:
        unsure_rate = 0.55
    else:
        unsure_rate = 0.15
    order = list(range(len(question.options)))
    rng.shuffle(order)
    return {
        "confidence": "unsure" if rng.random() < unsure_rate else "sure",
        "hint_used": bool(question.hint) and rng.random() < 0.15,
        "option_order": order,
    }


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
    exam = current_exam()
    rng = random.Random(20260915)
    random.seed(20260915)
    # Generador aparte para las señales de #13: si tirasen del mismo `rng`,
    # desplazarían todas las tiradas siguientes y cambiaría el perfil de
    # aciertos por dominio que la demostración fija a propósito.
    signals_rng = random.Random(20261011)
    # Y otro para «primero piensa» (#14), por el mismo motivo.
    recall_rng = random.Random(20261012)
    now = utcnow()
    total_attempts = 0

    for mode, count, days_ago in DEMO_SESSIONS:
        domain = rng.choice([d.number for d in exam.domains]) if mode == "dominio" else None
        if domain is not None:
            pool = (
                Question.query.join(Domain, Question.domain_id == Domain.id)
                .filter(Question.active.is_(True), Question.exam_id == exam.id, Domain.number == domain)
                .order_by(Question.id)
                .all()
            )
            rng.shuffle(pool)
            questions = pool[:count]
        else:
            questions = weighted_sample(exam, count)
        if not questions:
            continue

        started_at = now - timedelta(days=days_ago, hours=rng.randint(0, 10))
        study_session = StudySession(
            exam_id=exam.id,
            mode=mode,
            domain=domain,
            started_at=started_at,
            question_count=len(questions),
        )
        db.session.add(study_session)
        db.session.flush()  # necesitamos el id para los intentos

        # La mitad de las tandas que no son simulacro, en «primero piensa»:
        # así las métricas tienen con qué comparar.
        recall_first = mode != "simulacro" and recall_rng.random() < 0.5

        answered_at = started_at
        correct_count = 0
        for question in questions:
            is_correct = rng.random() < DEMO_ACCURACY.get(question.domain.number, DEMO_ACCURACY_DEFAULT)
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
                    **_demo_signals(question, is_correct, seconds, signals_rng),
                    recall_first=recall_first,
                    seconds_to_reveal=recall_rng.randint(5, min(40, seconds - 5)) if recall_first else None,
                )
            )
            correct_count += 1 if is_correct else 0
            total_attempts += 1

        study_session.finished_at = answered_at
        study_session.score_pct = round(correct_count / len(questions) * 100)

    db.session.commit()
    # Las respuestas sintéticas se insertan de golpe, no por /answer: el
    # estado FSRS se calcula después, igual que en un arranque.
    rebuild_review_states()
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
    # También los estados FSRS: si quedara alguno sin respuestas detrás, el
    # repaso de hoy seguiría ofreciendo preguntas de un progreso ya borrado.
    if not sessions and not attempts and not ReviewState.query.count():
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


@click.group("fsrs")
def fsrs_cli():
    """Repetición espaciada: mantenimiento del estado FSRS."""


@fsrs_cli.command("rebuild")
@with_appcontext
def fsrs_rebuild():
    """Reconstruye el estado FSRS de cada pregunta a partir de las respuestas.

    Idempotente: docker-start.sh lo lanza en cada arranque. Rellena la nota
    y la predicción de las respuestas que no las tienen (las anteriores a
    la repetición espaciada) y respeta las que ya están guardadas.
    """
    touched = rebuild_review_states()
    click.echo(
        f"Estado FSRS reconstruido: {touched['states']} preguntas con historial, "
        f"{touched['ratings_filled']} notas calculadas por primera vez, "
        f"{touched['states_removed']} estados sin respuestas eliminados."
    )


def _replay_table(columns):
    """Las métricas de cada configuración, una columna por configuración."""
    def fmt(value, kind):
        if value is None:
            return "—"
        if kind == "pct":
            return f"{value * 100:.1f} %"
        if kind == "num":
            return f"{value:.4f}"
        return str(value)

    rows = [
        ("Revisiones evaluadas", lambda r: r["metrics"] and r["metrics"]["reviews"], "int"),
        ("Log loss", lambda r: r["metrics"] and r["metrics"]["log_loss"], "num"),
        ("Log loss ingenuo", lambda r: r["metrics"] and r["metrics"]["baseline_log_loss"], "num"),
        ("RMSE por tramos", lambda r: r["metrics"] and r["metrics"]["rmse_bins"], "pct"),
        ("Acierto predicho", lambda r: r["metrics"] and r["metrics"]["predicted"], "pct"),
        ("Acierto real", lambda r: r["metrics"] and r["metrics"]["actual"], "pct"),
        ("Retención deseada", lambda r: r["desired_retention"], "pct"),
        ("Pendientes a 7 días", lambda r: r["due"][7], "int"),
        ("Pendientes a 30 días", lambda r: r["due"][30], "int"),
    ]
    width = max(len(label) for label, _f, _k in rows) + 2
    lines = [" " * width + "".join(f"{name:>14}" for name, _r in columns)]
    for label, get, kind in rows:
        lines.append(f"{label:<{width}}" + "".join(f"{fmt(get(r), kind):>14}" for _n, r in columns))
    return "\n".join(lines)


@fsrs_cli.command("replay")
@click.option("--exam", "exam_code", help="Código del examen. Por defecto, el activo.")
@click.option("--params", "params_file", type=click.Path(exists=True, dir_okay=False),
              help="JSON con los pesos de FSRS: la lista o {\"parameters\": [...]}.")
@click.option("--desired-retention", type=float, help="Retención deseada, entre 0.70 y 0.97.")
@click.option("--slow-factor", type=float, help="Un acierto más lento que esto por la referencia es Hard.")
@click.option("--fast-factor", type=float, help="Un acierto seguro más rápido que esto por la referencia es Easy.")
@with_appcontext
def fsrs_replay(exam_code, params_file, desired_retention, slow_factor, fast_factor):
    """Repite el historial con otra configuración y compara sus métricas con la vigente.

    No escribe nada en la base. Sin opciones, muestra solo la vigente.
    """
    if exam_code:
        exam = Exam.query.filter(db.func.upper(Exam.code) == exam_code.upper()).first()
        if exam is None:
            raise click.ClickException(f"No hay ningún examen con el código {exam_code}.")
    else:
        exam = current_exam()

    overrides = {k: v for k, v in (("slow_factor", slow_factor), ("fast_factor", fast_factor)) if v is not None}
    try:
        parameters = None
        if params_file:
            with open(params_file, encoding="utf-8") as fh:
                parameters = load_parameters(json.load(fh))
        current = replay(exam)
        columns = [("Vigente", current)]
        if parameters is not None or desired_retention is not None or overrides:
            columns.append(("Propuesta", replay(exam, parameters, desired_retention, overrides or None)))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{params_file} no es un JSON válido: {exc}") from exc
    except ReplayConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        # active_parameters() puede crear la fila de fábrica: no se guarda nada.
        db.session.rollback()

    click.echo(f"{exam.code}: {current['answers']} respuestas a {current['first_seen']} preguntas; "
               f"{current['same_day']} repeticiones a menos de un día no cuentan.")
    click.echo(_replay_table(columns))
    if current["metrics"] and not current["metrics"]["reliable"]:
        click.echo("Pocas revisiones todavía: las diferencias pequeñas entre configuraciones son ruido.")
    for name, result in columns:
        if result["metrics"]:
            click.echo(f"\nCalibración · {name} (tramo de predicción: revisiones, predicho → real)")
            for c in result["metrics"]["calibration"]:
                click.echo(f"  {c['low']:>3}-{c['high']:<3} %  {c['count']:>5}   "
                           f"{c['predicted'] * 100:5.1f} % → {c['actual'] * 100:5.1f} %")


def register_cli(app):
    app.cli.add_command(questions_cli)
    app.cli.add_command(fsrs_cli)
    app.cli.add_command(db_seed)
    app.cli.add_command(db_seed_demo)
    app.cli.add_command(db_reset_progress)
