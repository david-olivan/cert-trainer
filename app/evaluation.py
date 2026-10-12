"""Evaluación del algoritmo (issue #22): ¿acierta FSRS cuando predice?

En cada revisión, FSRS da una probabilidad de acierto antes de que
respondas; después se sabe si acertaste. Comparar las dos cosas sobre
todo el historial dice si el modelo está calibrado y permite elegir
entre configuraciones con datos en lugar de a ojo.

`replay()` repite el historial con una configuración (parámetros,
retención deseada, umbrales de nota) y devuelve sus métricas. La
configuración vigente es una más: así las cifras de dos configuraciones
se calculan siempre igual y se pueden comparar. No escribe nada.

Las revisiones a menos de un día de la anterior no cuentan: FSRS mide el
tiempo en días enteros y ahí predice siempre un 100 %, así que solo
añadirían ruido (el benchmark de FSRS también las aparta).
"""
import math
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating
from fsrs.scheduler import DEFAULT_PARAMETERS

from app import srs
from app.models import Attempt, Question

BINS = 10
# Las predicciones se acotan para que un 0 % o un 100 % fallado no dé un log loss infinito.
EPS = 1e-6
FORECAST_DAYS = (7, 30)
# Por debajo, las métricas oscilan demasiado para sacar conclusiones.
MIN_RELIABLE_REVIEWS = 100


class ReplayConfigError(ValueError):
    """Una configuración de repetición que no se puede usar, con el motivo."""


def _log_loss(pairs, predict):
    total = 0.0
    for p, y in pairs:
        p = min(1 - EPS, max(EPS, predict(p)))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(pairs)


def evaluate(pairs):
    """Métricas de un conjunto de pares (probabilidad predicha, 1 si se acertó o 0).

    - log_loss: cuanto más bajo, mejor. `baseline_log_loss` es el de
      predecir siempre la tasa media de acierto: si FSRS no lo mejora, no
      está aportando nada.
    - rmse_bins: el «RMSE (bins)» del benchmark de FSRS, simplificado. Se
      agrupan las revisiones en tramos de predicción del 10 % y se mide la
      distancia entre la predicción media y el acierto real de cada tramo,
      ponderada por cuántas revisiones tiene.
    - calibration: los tramos con revisiones, para la curva de calibración.
    """
    if not pairs:
        return None
    n = len(pairs)
    actual = sum(y for _p, y in pairs) / n
    bins = [[0, 0.0, 0] for _ in range(BINS)]
    for p, y in pairs:
        b = bins[min(BINS - 1, int(p * BINS))]
        b[0] += 1
        b[1] += p
        b[2] += y
    calibration = [
        {
            "low": round(i / BINS * 100),
            "high": round((i + 1) / BINS * 100),
            "count": count,
            "predicted": sum_p / count,
            "actual": sum_y / count,
        }
        for i, (count, sum_p, sum_y) in enumerate(bins)
        if count
    ]
    rmse = math.sqrt(sum(c["count"] * (c["predicted"] - c["actual"]) ** 2 for c in calibration) / n)
    return {
        "reviews": n,
        "log_loss": _log_loss(pairs, lambda p: p),
        "baseline_log_loss": _log_loss(pairs, lambda _p: actual),
        "rmse_bins": rmse,
        "predicted": sum(p for p, _y in pairs) / n,
        "actual": actual,
        "calibration": calibration,
        "reliable": n >= MIN_RELIABLE_REVIEWS,
    }


def load_parameters(raw):
    """Los pesos de un JSON: la lista tal cual o {"parameters": [...]}, como los guarda la base."""
    parameters = raw.get("parameters") if isinstance(raw, dict) else raw
    if not isinstance(parameters, list) or not all(isinstance(w, (int, float)) for w in parameters):
        raise ReplayConfigError(
            "El fichero de parámetros tiene que ser una lista de números o un objeto con la clave "
            "«parameters» que la contenga."
        )
    if len(parameters) != len(DEFAULT_PARAMETERS):
        raise ReplayConfigError(
            f"FSRS necesita {len(DEFAULT_PARAMETERS)} parámetros y el fichero trae {len(parameters)}."
        )
    return [float(w) for w in parameters]


def replay(exam, parameters=None, desired_retention=None, rating_overrides=None, now=None):
    """Repite el historial de `exam` con una configuración y mide sus predicciones.

    Lo que no se pasa sale de la configuración activa. Con umbrales de nota
    nuevos (`rating_overrides`), todas las notas se recalculan con ellos;
    si no, se usan las guardadas, que son las que de verdad se dieron.

    La retención deseada no cambia las predicciones (dependen de las notas
    y de cuándo respondiste, que es historia), sino cuándo se programa cada
    repaso: por eso el resultado incluye cuántos tocarían en los próximos
    días.
    """
    now = srs.utc(now or datetime.now(timezone.utc))
    params = srs.active_parameters(exam)
    parameters = parameters if parameters is not None else params.parameters
    retention = desired_retention if desired_retention is not None else exam.desired_retention
    if not 0.7 <= retention <= 0.97:
        raise ReplayConfigError(f"La retención deseada tiene que estar entre 0.70 y 0.97, no {retention}.")
    config = {**srs.rating_config(params), **(rating_overrides or {})}
    scheduler = srs.make_scheduler(parameters, retention)
    reference = srs.reference_seconds(exam, config)

    attempts = (
        Attempt.query.join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .order_by(Attempt.question_id, Attempt.answered_at, Attempt.id)
        .all()
    )
    cards = {}
    pairs = []
    same_day = 0
    for attempt in attempts:
        when = srs.utc(attempt.answered_at)
        card = cards.get(attempt.question_id)
        if card is None:
            card = Card(card_id=attempt.question_id, due=when)
        elif when - srs.utc(card.last_review) < timedelta(days=1):
            same_day += 1
        else:
            pairs.append((scheduler.get_card_retrievability(card, when), int(attempt.is_correct)))

        if attempt.rating and not rating_overrides:
            rating = Rating(attempt.rating)
        else:
            rating = srs.rating_for(
                attempt.is_correct, attempt.confidence, attempt.hint_used, attempt.seconds_spent, reference, config,
            )
        card, _log = scheduler.review_card(card, rating, when)
        cards[attempt.question_id] = card

    for card in cards.values():
        srs.cap_due(card, exam, now)
    return {
        "metrics": evaluate(pairs),
        "answers": len(attempts),
        "first_seen": len(cards),
        "same_day": same_day,
        "desired_retention": retention,
        "rating_config": config,
        "due": {days: sum(1 for c in cards.values() if c.due < now + timedelta(days=days)) for days in FORECAST_DAYS},
    }
