"""Repetición espaciada con FSRS (issue #16).

Cada respuesta es una revisión: se traduce a una nota FSRS (Again, Hard,
Good o Easy) y actualiza el estado de la pregunta, que dice cuándo toca
volver a verla y con qué probabilidad se acertaría hoy.

Attempt es el registro de revisiones y ReviewState es derivable de él:
`rebuild()` lo reconstruye entero. Por eso el reparto es sencillo:
- `review()` se llama al responder, en la misma transacción que guarda el
  Attempt.
- `rebuild()` lo lanza `flask fsrs rebuild` en cada arranque y después de
  cambiar parámetros. Es determinista: sin «fuzz» en los intervalos, dos
  reconstrucciones dan exactamente lo mismo.
"""
from datetime import datetime, time, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from fsrs import Card, Rating, Scheduler, State
from fsrs.scheduler import DEFAULT_PARAMETERS

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import Attempt, Exam, FsrsParameters, Question, ReviewState

# Umbrales con que se deduce la nota. Son los primeros mandos que ajustar
# con las métricas (#22): cada examen guarda su copia en
# FsrsParameters.rating_config, y estos son los valores con que nace.
DEFAULT_RATING_CONFIG = {
    # Un acierto que tarda más de slow_factor veces tu tiempo de referencia
    # cuenta como «lento» (Hard); uno seguro por debajo de fast_factor veces,
    # como «rápido» (Easy).
    "slow_factor": 1.5,
    "fast_factor": 0.5,
    # El tiempo de referencia es la mediana de tus últimas respuestas en el
    # examen. Con menos de min_samples se usa fallback_seconds, y nunca baja
    # de min_reference_seconds: con una referencia de 0 s, cualquier acierto
    # contaría como lento.
    "median_window": 200,
    "min_samples": 20,
    "fallback_seconds": 60,
    "min_reference_seconds": 10,
}


def utc(dt):
    """La fecha en UTC con el tzinfo que exige fsrs (timezone.utc, no otro).

    sqlite devuelve fechas sin zona y Postgres con la suya propia; fsrs
    rechaza las dos.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def active_parameters(exam):
    """Los parámetros activos del examen; si no tiene, nacen con los de fábrica."""
    params = FsrsParameters.query.filter_by(exam_id=exam.id, active=True).order_by(FsrsParameters.id.desc()).first()
    if params is None:
        params = FsrsParameters(
            exam_id=exam.id,
            parameters=list(DEFAULT_PARAMETERS),
            rating_config=dict(DEFAULT_RATING_CONFIG),
            source="default",
            review_count=0,
            active=True,
        )
        db.session.add(params)
        db.session.flush()
    return params


def scheduler_for(exam, params):
    return make_scheduler(params.parameters, exam.desired_retention)


def make_scheduler(parameters, desired_retention):
    """El planificador con que trabaja la aplicación, para unos pesos y una retención dados."""
    return Scheduler(
        parameters=parameters,
        desired_retention=desired_retention,
        # Sin pasos de aprendizaje (por defecto, 1 y 10 minutos): sirven para
        # repetir una tarjeta varias veces en la misma sesión, y aquí una
        # tanda no repite preguntas y se estudia por días. Con ellos, cada
        # pregunta acertada volvía a tocar a los 10 minutos y hacía falta
        # acertarla dos veces antes de espaciarla. Sin ellos: un fallo vuelve
        # mañana, un acierto a los 2 días y uno fácil a los 8.
        learning_steps=(),
        relearning_steps=(),
        # Sin fuzz: sirve para repartir carga entre miles de tarjetas, y
        # aquí rompería que rebuild() sea reproducible.
        enable_fuzzing=False,
    )


def rating_config(params):
    """Los umbrales para deducir la nota, con los de fábrica para lo que falte."""
    return {**DEFAULT_RATING_CONFIG, **(params.rating_config or {})}


def reference_seconds(exam, config):
    """Mediana de los segundos de tus últimas respuestas en el examen."""
    rows = (
        db.session.query(Attempt.seconds_spent)
        .join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id, Attempt.seconds_spent.isnot(None))
        .order_by(Attempt.answered_at.desc(), Attempt.id.desc())
        .limit(config["median_window"])
        .all()
    )
    if len(rows) < config["min_samples"]:
        return config["fallback_seconds"]
    return max(config["min_reference_seconds"], median(seconds for (seconds,) in rows))


def rating_for(is_correct, confidence, hint_used, seconds_spent, reference, config):
    """La nota FSRS que merece una respuesta.

    | Respuesta                                 | Nota  |
    |-------------------------------------------|-------|
    | Fallo o en blanco                         | Again |
    | Acierto con «dudo», con pista o lento     | Hard  |
    | Acierto seguro y rápido                   | Easy  |
    | Cualquier otro acierto                    | Good  |

    Sin confianza registrada (intentos anteriores a #13) cuenta como
    «seguro»; sin tiempo, ni lento ni rápido.
    """
    if not is_correct:
        return Rating.Again
    slow = seconds_spent is not None and seconds_spent > config["slow_factor"] * reference
    fast = seconds_spent is not None and seconds_spent < config["fast_factor"] * reference
    if confidence == "unsure" or hint_used or slow:
        return Rating.Hard
    if fast:
        return Rating.Easy
    return Rating.Good


def cap_due(card, exam, now):
    """Ningún repaso después del examen: lo que caería más allá, se adelanta a la víspera.

    Si el examen es hoy o ya pasó, no se toca nada.
    """
    if exam.exam_date is None:
        return card
    exam_starts = datetime.combine(exam.exam_date, time.min, tzinfo=timezone.utc)
    if exam_starts <= now or card.due < exam_starts:
        return card
    card.due = max(now, exam_starts - timedelta(days=1))
    return card


def _card_from(state, question_id):
    return Card(
        card_id=question_id,
        state=State(state.state),
        step=state.step,
        stability=state.stability,
        difficulty=state.difficulty,
        due=utc(state.due),
        last_review=utc(state.last_review),
    )


def _store(state, card):
    state.state = int(card.state)
    state.step = card.step
    state.stability = card.stability
    state.difficulty = card.difficulty
    state.due = card.due
    state.last_review = card.last_review


def _predicted(scheduler, card, when):
    """Probabilidad de acierto que FSRS da a la tarjeta en `when`, o None si nunca se vio."""
    if card.last_review is None:
        return None
    return scheduler.get_card_retrievability(card, when)


def _duration_ms(seconds_spent):
    return seconds_spent * 1000 if isinstance(seconds_spent, int) and seconds_spent >= 0 else None


def review(attempt, question, exam, now=None):
    """Aplica una respuesta recién dada al estado FSRS de su pregunta.

    Rellena attempt.rating y attempt.predicted_r y actualiza (o crea) el
    ReviewState. No hace commit: lo hace quien guarda el Attempt, para que
    los dos entren en la misma transacción.
    """
    now = utc(now or datetime.now(timezone.utc))
    params = active_parameters(exam)
    config = rating_config(params)
    scheduler = scheduler_for(exam, params)

    state = ReviewState.query.filter_by(question_id=question.id).first()
    card = _card_from(state, question.id) if state else Card(card_id=question.id, due=now)

    attempt.predicted_r = _predicted(scheduler, card, now)
    rating = rating_for(
        attempt.is_correct, attempt.confidence, attempt.hint_used, attempt.seconds_spent,
        reference_seconds(exam, config), config,
    )
    attempt.rating = int(rating)

    card, _log = scheduler.review_card(card, rating, now, _duration_ms(attempt.seconds_spent))
    cap_due(card, exam, now)

    if state is None:
        state = ReviewState(question_id=question.id)
        db.session.add(state)
    _store(state, card)
    return state


def rebuild(exams=None, now=None):
    """Reconstruye el estado FSRS de todas las preguntas a partir de Attempt.

    Las notas y predicciones que ya estén guardadas se respetan: solo se
    calculan las que faltan (intentos anteriores a #16). Así repetirla no
    cambia nada, y el estado que deja es el mismo que habría dejado ir
    respondiendo una a una. Devuelve cuántos estados y notas tocó.
    """
    now = utc(now or datetime.now(timezone.utc))
    exams = exams if exams is not None else Exam.query.order_by(Exam.id).all()
    touched = {"states": 0, "ratings_filled": 0, "states_removed": 0}

    for exam in exams:
        params = active_parameters(exam)
        config = rating_config(params)
        scheduler = scheduler_for(exam, params)
        reference = reference_seconds(exam, config)

        attempts = (
            Attempt.query.join(Question, Attempt.question_id == Question.id)
            .filter(Question.exam_id == exam.id)
            .order_by(Attempt.question_id, Attempt.answered_at, Attempt.id)
            .all()
        )
        cards = {}
        for attempt in attempts:
            card = cards.get(attempt.question_id) or Card(card_id=attempt.question_id, due=utc(attempt.answered_at))
            when = utc(attempt.answered_at)
            if attempt.predicted_r is None:
                attempt.predicted_r = _predicted(scheduler, card, when)
            if attempt.rating is None:
                attempt.rating = int(rating_for(
                    attempt.is_correct, attempt.confidence, attempt.hint_used, attempt.seconds_spent,
                    reference, config,
                ))
                touched["ratings_filled"] += 1
            card, _log = scheduler.review_card(card, Rating(attempt.rating), when, _duration_ms(attempt.seconds_spent))
            cards[attempt.question_id] = card

        existing = {
            s.question_id: s
            for s in ReviewState.query.join(Question, ReviewState.question_id == Question.id).filter(
                Question.exam_id == exam.id
            )
        }
        for question_id, card in cards.items():
            cap_due(card, exam, now)
            state = existing.pop(question_id, None)
            if state is None:
                state = ReviewState(question_id=question_id)
                db.session.add(state)
            _store(state, card)
            touched["states"] += 1
        # Estados sin ninguna respuesta detrás (por ejemplo, tras borrar el
        # progreso): sobran.
        for state in existing.values():
            db.session.delete(state)
            touched["states_removed"] += 1

    db.session.commit()
    return touched


# ---------------------------------------------------------------------------
# «Repaso de hoy» (issue #17)
# ---------------------------------------------------------------------------

FORECAST_DAYS = 7


def local_tz():
    return ZoneInfo(current_app.config["TIMEZONE"])


def day_end(now, tz, days_ahead=0):
    """Instante UTC en que acaba el día local de `now` (más `days_ahead` días).

    «Hoy» es el día local, no las próximas 24 horas: una pregunta que vence
    esta tarde ya está pendiente por la mañana, como en Anki.
    """
    local_date = utc(now).astimezone(tz).date() + timedelta(days=days_ahead + 1)
    return datetime.combine(local_date, time.min, tzinfo=tz).astimezone(timezone.utc)


def _states_of_active_questions(exam):
    return (
        ReviewState.query.join(Question, ReviewState.question_id == Question.id)
        .filter(Question.exam_id == exam.id, Question.active.is_(True))
        .all()
    )


def _new_seen_today(exam, now, tz):
    """Cuántas preguntas se vieron hoy por primera vez: gastan cupo de nuevas."""
    today_starts = day_end(now, tz, days_ahead=-1)
    first_seen = (
        db.session.query(func.min(Attempt.answered_at))
        .join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .group_by(Attempt.question_id)
        .all()
    )
    return sum(1 for (first,) in first_seen if utc(first) >= today_starts)


def daily_review(exam, now=None):
    """Lo que toca hoy: (pendientes, nuevas).

    Pendientes: las preguntas que vencen antes de que acabe el día local,
    de la que menos probabilidad tiene de acertarse a la que más. Nuevas:
    hasta `exam.new_per_day` nunca vistas, descontadas las que ya se
    estrenaron hoy, muestreadas con el peso de cada dominio.
    """
    from app.sampling import weighted_sample

    now = utc(now or datetime.now(timezone.utc))
    tz = local_tz()
    until = day_end(now, tz)
    scheduler = scheduler_for(exam, active_parameters(exam))

    due_states = [s for s in _states_of_active_questions(exam) if utc(s.due) < until]
    due_states.sort(key=lambda s: (scheduler.get_card_retrievability(_card_from(s, s.question_id), now), s.question_id))
    due = [s.question for s in due_states]

    remaining_new = max(0, exam.new_per_day - _new_seen_today(exam, now, tz))
    new = []
    if remaining_new:
        seen_ids = {s.question_id for s in ReviewState.query.join(Question).filter(Question.exam_id == exam.id)}
        unseen_by_domain = {d.number: [] for d in exam.domains}
        number_by_domain_id = {d.id: d.number for d in exam.domains}
        for q in Question.query.filter_by(exam_id=exam.id, active=True):
            if q.id not in seen_ids:
                unseen_by_domain[number_by_domain_id[q.domain_id]].append(q)
        available = sum(len(pool) for pool in unseen_by_domain.values())
        new = weighted_sample(exam, min(remaining_new, available), pool_by_domain=unseen_by_domain)
    return due, new


def retrievability(exam, when=None):
    """Probabilidad de acierto de cada pregunta activa ya vista, en `when` (por defecto, ahora).

    {question_id: R}. Las nunca vistas no salen: FSRS no sabe nada de ellas.
    """
    when = utc(when or datetime.now(timezone.utc))
    scheduler = scheduler_for(exam, active_parameters(exam))
    return {
        s.question_id: scheduler.get_card_retrievability(_card_from(s, s.question_id), when)
        for s in _states_of_active_questions(exam)
    }


def scheduled_dues(exam):
    """Para qué fecha quedó programado el repaso tras cada respuesta del examen.

    Rehace la historia como rebuild(), con los parámetros activos y sin
    escribir nada. Sirve para comparar la carga prevista con la hecha (#21):
    el vencimiento de cada pregunta solo se guarda para el último repaso.
    """
    params = active_parameters(exam)
    config = rating_config(params)
    scheduler = scheduler_for(exam, params)
    reference = reference_seconds(exam, config)
    attempts = (
        Attempt.query.join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .order_by(Attempt.question_id, Attempt.answered_at, Attempt.id)
        .all()
    )
    cards = {}
    dues = []
    for attempt in attempts:
        when = utc(attempt.answered_at)
        card = cards.get(attempt.question_id) or Card(card_id=attempt.question_id, due=when)
        rating = attempt.rating or int(rating_for(
            attempt.is_correct, attempt.confidence, attempt.hint_used, attempt.seconds_spent, reference, config,
        ))
        card, _log = scheduler.review_card(card, Rating(rating), when, _duration_ms(attempt.seconds_spent))
        cap_due(card, exam, when)
        cards[attempt.question_id] = card
        dues.append(utc(card.due))
    return dues


def review_summary(exam, now=None):
    """Cifras de la portada: pendientes y nuevas de hoy y previsión de los próximos días.

    `forecast` tiene FORECAST_DAYS entradas (fecha local, cuántas vencen ese
    día); la de hoy incluye las atrasadas.
    """
    now = utc(now or datetime.now(timezone.utc))
    tz = local_tz()
    due, new = daily_review(exam, now)
    ends = [day_end(now, tz, i) for i in range(FORECAST_DAYS)]
    counts = [0] * FORECAST_DAYS
    for state in _states_of_active_questions(exam):
        state_due = utc(state.due)
        for i, end in enumerate(ends):
            if state_due < end:
                counts[i] += 1
                break
    today = utc(now).astimezone(tz).date()
    return {
        "due": len(due),
        "new": len(new),
        "total": len(due) + len(new),
        "forecast": [(today + timedelta(days=i), counts[i]) for i in range(FORECAST_DAYS)],
    }
