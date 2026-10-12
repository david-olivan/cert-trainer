"""Panel de métricas (issue #21): qué sabes, cómo está el banco y cómo estudias.

Todo sale de Attempt, el registro de respuestas, y del estado FSRS que se
deriva de él. Nada se guarda: cada cifra se calcula al abrir la página,
que con un solo usuario cuesta poco.

Cualquier cifra que se parezca a una nota es una estimación, nunca una
predicción del resultado (CLAUDE.md): la plantilla lo dice al lado.
"""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from statistics import median

from app import srs
from app.evaluation import replay
from app.extensions import db
from app.kit import coverage
from app.models import Attempt, Question

# Con menos respuestas, «nunca se falla» no dice nada.
NEVER_FAILED_MIN_ATTEMPTS = 3
# Un distractor elegido una sola vez es un despiste, no un patrón.
DISTRACTOR_MIN_PICKS = 2
TOP = 10
# Límites superiores de los tramos del histograma de tiempos, en segundos.
TIME_BUCKETS = (15, 30, 45, 60, 90, 120, 180)
HABIT_DAYS = 28
LOAD_DAYS = 14
# Hora local a la que se supone el examen para la proyección.
EXAM_HOUR = time(9)


def _rate(correct, total):
    return {"correct": correct, "total": total, "pct": round(correct / total * 100) if total else None}


def _rows(exam):
    """(Attempt, Question) del examen, en el orden en que se respondieron."""
    return (
        db.session.query(Attempt, Question)
        .join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .order_by(Attempt.answered_at, Attempt.id)
        .all()
    )


def _first_sight_by_domain(exam):
    """Acierto en la primera respuesta a cada pregunta, por número de dominio.

    Consulta ligera (sin cargar objetos) para la portada.
    """
    number_of = {d.id: d.number for d in exam.domains}
    rows = (
        db.session.query(Attempt.question_id, Attempt.is_correct, Question.domain_id)
        .join(Question, Attempt.question_id == Question.id)
        .filter(Question.exam_id == exam.id)
        .order_by(Attempt.answered_at, Attempt.id)
        .all()
    )
    seen = set()
    tally = {n: [0, 0] for n in number_of.values()}
    for question_id, is_correct, domain_id in rows:
        if question_id in seen:
            continue
        seen.add(question_id)
        tally[number_of[domain_id]][0] += int(is_correct)
        tally[number_of[domain_id]][1] += 1
    return {n: _rate(*t) for n, t in tally.items()}


def readiness(exam, when=None, first_sight=None):
    """Probabilidad media de acertar las preguntas del banco de cada dominio en `when`.

    Las ya vistas cuentan con la probabilidad de FSRS; las que aún no has
    visto, con tu acierto en primera vista en ese dominio, que es lo mejor
    que se sabe de cómo te va con una pregunta nueva. Sin ninguna respuesta
    en el dominio, None.

    Devuelve {número: {"pct", "seen", "total"}} y, en "overall", la media
    ponderada por el peso oficial de los dominios con cifra.
    """
    first_sight = first_sight if first_sight is not None else _first_sight_by_domain(exam)
    r_by_question = srs.retrievability(exam, when)
    number_of = {d.id: d.number for d in exam.domains}
    active = defaultdict(list)
    for question_id, domain_id in (
        Question.query.filter_by(exam_id=exam.id, active=True).with_entities(Question.id, Question.domain_id)
    ):
        active[number_of[domain_id]].append(question_id)

    out = {}
    for d in exam.domains:
        ids = active[d.number]
        seen = [r_by_question[i] for i in ids if i in r_by_question]
        rate = first_sight.get(d.number)
        fs = rate["correct"] / rate["total"] if rate and rate["total"] else None
        if not ids or (not seen and fs is None):
            pct = None
        elif fs is None:
            pct = round(sum(seen) / len(seen) * 100)
        else:
            pct = round((sum(seen) + (len(ids) - len(seen)) * fs) / len(ids) * 100)
        out[d.number] = {"pct": pct, "seen": len(seen), "total": len(ids)}

    weighted = [(d.weight, out[d.number]["pct"]) for d in exam.domains if out[d.number]["pct"] is not None]
    weight_sum = sum(w for w, _ in weighted)
    out["overall"] = round(sum(w * p for w, p in weighted) / weight_sum) if weight_sum else None
    return out


def projection(exam, now, first_sight):
    """La misma estimación que el medidor, el día del examen y sin repasar nada más.

    Es un suelo, no una previsión: cada repaso de aquí al examen la sube.
    None si no hay fecha o el examen ya pasó.
    """
    if exam.exam_date is None:
        return None
    tz = srs.local_tz()
    when = datetime.combine(exam.exam_date, EXAM_HOUR, tzinfo=tz).astimezone(timezone.utc)
    if when <= now:
        return None
    estimate = readiness(exam, when, first_sight)
    return {"date": exam.exam_date, "days": (exam.exam_date - now.astimezone(tz).date()).days, **estimate}


def _first_sight(exam, rows):
    number_of = {d.id: d.number for d in exam.domains}
    firsts = {}
    for a, q in rows:
        firsts.setdefault(q.id, (a, q))
    by_domain = {d.number: [0, 0] for d in exam.domains}
    by_skill = defaultdict(lambda: [0, 0])
    for a, q in firsts.values():
        for tally in (by_domain[number_of[q.domain_id]], by_skill[(number_of[q.domain_id], q.skill)]):
            tally[0] += int(a.is_correct)
            tally[1] += 1
    overall = [sum(t[0] for t in by_domain.values()), sum(t[1] for t in by_domain.values())]
    return {
        "overall": _rate(*overall),
        "by_domain": {n: _rate(*t) for n, t in by_domain.items()},
        "by_skill": {k: _rate(*t) for k, t in by_skill.items()},
    }


def _skills(exam, rows, first_sight):
    """Cobertura y acierto en primera vista por habilidad, dominio a dominio."""
    number_of = {d.id: d.number for d in exam.domains}
    bank = Counter()
    for q in Question.query.filter_by(exam_id=exam.id, active=True):
        bank[(number_of[q.domain_id], q.skill)] += 1
    seen = Counter()
    for q in {q.id: q for _a, q in rows if q.active}.values():
        seen[(number_of[q.domain_id], q.skill)] += 1
    out = []
    for d in exam.domains:
        described = {s.code: s.description for s in d.skills}
        codes = set(described) | {skill for (number, skill) in bank if number == d.number}
        items = [
            {
                "code": code,
                "description": described.get(code),
                "bank": bank[(d.number, code)],
                "seen": seen[(d.number, code)],
                "first_sight": first_sight["by_skill"].get((d.number, code), _rate(0, 0)),
            }
            for code in sorted(codes)
        ]
        out.append({"domain": d, "skills": items, "empty": sum(1 for i in items if not i["bank"])})
    return out


def _recall_first(rows):
    """Acierto con «primero piensa» frente a sin él. Antes de #14 no existía: cuenta como sin."""
    groups = {True: [0, 0, []], False: [0, 0, []]}
    for a, _q in rows:
        g = groups[bool(a.recall_first)]
        g[0] += int(a.is_correct)
        g[1] += 1
        if a.seconds_spent is not None:
            g[2].append(a.seconds_spent)
    return {
        key: {**_rate(c, t), "median_seconds": round(median(s)) if s else None}
        for key, (c, t, s) in groups.items()
    }


def _option_text(q, index):
    return q.options[index] if 0 <= index < len(q.options) else "?"


def _sure_failures(rows):
    """Fallos con «seguro»: errores de concepto, lo primero que repasar. Por pregunta."""
    by_question = {}
    for a, q in rows:
        if a.confidence == "sure" and not a.is_correct:
            entry = by_question.setdefault(q.id, {"question": q, "count": 0})
            entry["count"] += 1
            entry["last"] = a.answered_at
            entry["picked"] = [_option_text(q, i) for i in a.selected]
    # Primero las que más veces se han fallado así; a igualdad, la más reciente.
    items = sorted(by_question.values(), key=lambda e: e["last"], reverse=True)
    items.sort(key=lambda e: -e["count"])
    return {"total": sum(e["count"] for e in items), "questions": items[:TOP]}


def _percentile(sorted_values, fraction):
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def _timing(exam, rows):
    timed = [(a, q) for a, q in rows if a.seconds_spent is not None]
    if not timed:
        return None
    seconds = sorted(a.seconds_spent for a, _q in timed)
    config = srs.rating_config(srs.active_parameters(exam))
    reference = srs.reference_seconds(exam, config)
    slow_limit = config["slow_factor"] * reference
    budget = exam.minutes_per_question * 60

    bounds = (0,) + TIME_BUCKETS
    buckets = []
    for i, upper in enumerate(TIME_BUCKETS + (None,)):
        lower = bounds[i]
        count = sum(1 for s in seconds if s >= lower and (upper is None or s < upper))
        buckets.append({"label": f"{lower}–{upper}" if upper else f"≥{lower}", "count": count})
    peak = max(b["count"] for b in buckets) or 1
    for b in buckets:
        b["height"] = round(b["count"] / peak * 100)

    number_of = {d.id: d.number for d in exam.domains}
    per_domain = defaultdict(list)
    slow = {}
    for a, q in timed:
        per_domain[number_of[q.domain_id]].append(a.seconds_spent)
        if a.is_correct and a.seconds_spent > slow_limit:
            entry = slow.setdefault(q.id, {"question": q, "count": 0, "max": 0})
            entry["count"] += 1
            entry["max"] = max(entry["max"], a.seconds_spent)
    return {
        "count": len(seconds),
        "median": round(median(seconds)),
        "p90": _percentile(seconds, 0.9),
        "budget": budget,
        "over_budget": _rate(sum(1 for s in seconds if s > budget), len(seconds)),
        "reference": round(reference),
        "slow_limit": round(slow_limit),
        "buckets": buckets,
        "per_domain": {d.number: round(median(per_domain[d.number])) if per_domain[d.number] else None
                       for d in exam.domains},
        "slow": sorted(slow.values(), key=lambda e: (-e["count"], -e["max"]))[:TOP],
        "slow_total": sum(e["count"] for e in slow.values()),
    }


def _distractors(rows):
    """La opción incorrecta más elegida de cada pregunta que se ha fallado."""
    picks = defaultdict(Counter)
    answered = Counter()
    questions = {}
    for a, q in rows:
        questions[q.id] = q
        answered[q.id] += 1
        for i in set(a.selected) - set(q.correct):
            picks[q.id][i] += 1
    items = []
    for q_id, counter in picks.items():
        index, count = counter.most_common(1)[0]
        if count < DISTRACTOR_MIN_PICKS:
            continue
        q = questions[q_id]
        items.append({"question": q, "option": _option_text(q, index), "count": count, "answered": answered[q_id]})
    items.sort(key=lambda e: (-e["count"], -e["count"] / e["answered"], e["question"].ext_id))
    return items[:TOP]


def _never_failed(rows):
    stats = defaultdict(lambda: [0, 0])
    questions = {}
    for a, q in rows:
        questions[q.id] = q
        stats[q.id][0] += 1
        stats[q.id][1] += int(not a.is_correct)
    items = [
        {"question": questions[q_id], "answered": n}
        for q_id, (n, failed) in stats.items()
        if n >= NEVER_FAILED_MIN_ATTEMPTS and not failed
    ]
    items.sort(key=lambda e: (-e["answered"], e["question"].ext_id))
    return items


def _position_bias(rows):
    """Por número de opciones: en qué posición mostrada eliges y en cuál estaba la correcta.

    Las opciones se barajan, así que la correcta cae en cualquier posición
    por igual. Si eliges una posición mucho más que las demás, hay sesgo.
    """
    groups = {}
    for a, q in rows:
        order = a.option_order
        if not order or sorted(order) != list(range(len(q.options))):
            continue
        position_of = {original: shown for shown, original in enumerate(order)}
        g = groups.setdefault(len(order), {"answers": 0, "chosen": Counter(), "correct": Counter()})
        g["answers"] += 1
        for i in a.selected:
            if i in position_of:
                g["chosen"][position_of[i]] += 1
        for i in q.correct:
            g["correct"][position_of[i]] += 1
    out = []
    for n in sorted(groups):
        g = groups[n]
        chosen_total = sum(g["chosen"].values()) or 1
        correct_total = sum(g["correct"].values()) or 1
        out.append({
            "options": n,
            "answers": g["answers"],
            "positions": [
                {
                    "letter": chr(65 + p),
                    "chosen": round(g["chosen"][p] / chosen_total * 100),
                    "correct": round(g["correct"][p] / correct_total * 100),
                }
                for p in range(n)
            ],
            "expected": round(100 / n),
        })
    return out


def _formats(exam):
    cov = coverage(exam)
    total = cov["total"]
    return [
        {
            "options": f.option_count,
            "correct": f.correct_count,
            "count": cov["per_shape"].get((f.option_count, f.correct_count), 0),
            "pct": round(cov["per_shape"].get((f.option_count, f.correct_count), 0) / total * 100) if total else None,
            "target": None if f.target_share is None else round(f.target_share * 100),
        }
        for f in exam.formats
    ]


def _habit(exam, rows, now):
    """Respuestas por día y carga prevista frente a la hecha, en días locales."""
    tz = srs.local_tz()
    today = now.astimezone(tz).date()

    def local_day(dt):
        return srs.utc(dt).astimezone(tz).date()

    seen = set()
    new_by_day = Counter()
    repeat_by_day = Counter()
    for a, q in rows:
        day = local_day(a.answered_at)
        (repeat_by_day if q.id in seen else new_by_day)[day] += 1
        seen.add(q.id)

    days = [today - timedelta(days=i) for i in range(HABIT_DAYS - 1, -1, -1)]
    per_day = [{"day": d, "new": new_by_day[d], "repeat": repeat_by_day[d]} for d in days]
    peak = max((e["new"] + e["repeat"] for e in per_day), default=0) or 1
    for e in per_day:
        e["total"] = e["new"] + e["repeat"]
        e["height"] = round(e["total"] / peak * 100)

    due_by_day = Counter(local_day(due) for due in srs.scheduled_dues(exam))
    load_days = days[-LOAD_DAYS:]
    load = [{"day": d, "due": due_by_day[d], "done": repeat_by_day[d]} for d in load_days]
    load_peak = max((max(e["due"], e["done"]) for e in load), default=0) or 1
    for e in load:
        e["due_height"] = round(e["due"] / load_peak * 100)
        e["done_height"] = round(e["done"] / load_peak * 100)

    return {
        "per_day": per_day,
        "active_days": sum(1 for e in per_day if e["total"]),
        "answers": sum(e["total"] for e in per_day),
        "load": load,
        "load_due": sum(e["due"] for e in load),
        "load_done": sum(e["done"] for e in load),
    }


def _algorithm(exam, now):
    """Cómo de bien predice FSRS con la configuración activa (#22)."""
    result = replay(exam, now=now)
    params = srs.active_parameters(exam)
    calibration = (result["metrics"] or {}).get("calibration", [])
    for c in calibration:
        c["predicted_height"] = round(c["predicted"] * 100)
        c["actual_height"] = round(c["actual"] * 100)
    return {**result, "source": params.source, "fitted_on": params.review_count}


def dashboard(exam, now=None):
    """Todo lo que pinta la página de métricas de `exam`."""
    now = srs.utc(now or datetime.now(timezone.utc))
    rows = _rows(exam)
    first_sight_domain = _first_sight_by_domain(exam)
    data = {
        "answers": len(rows),
        "questions_seen": len({q.id for _a, q in rows}),
        "bank": Question.query.filter_by(exam_id=exam.id, active=True).count(),
        "formats": _formats(exam),
    }
    if not rows:
        return data
    first_sight = _first_sight(exam, rows)
    data.update(
        readiness=readiness(exam, now, first_sight_domain),
        projection=projection(exam, now, first_sight_domain),
        first_sight=first_sight,
        skills=_skills(exam, rows, first_sight),
        recall_first=_recall_first(rows),
        sure_failures=_sure_failures(rows),
        timing=_timing(exam, rows),
        distractors=_distractors(rows),
        never_failed=_never_failed(rows),
        position_bias=_position_bias(rows),
        habit=_habit(exam, rows, now),
        algorithm=_algorithm(exam, now),
    )
    return data
