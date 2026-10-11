"""Alta y edición de exámenes (issue #19): leer el formulario, validarlo y aplicarlo.

Vive aparte de la vista para poder probarlo sin navegador. El formulario
llega con filas numeradas para dominios y formatos (`domain-0-name`,
`format-1-option_count`…), que el JavaScript de la página añade al pulsar
«Añadir»; aquí se agrupan por índice.

Reglas que protegen el banco:
- Los pesos de los dominios suman 100.
- Un dominio o un formato que ya usan preguntas no se puede quitar, y un
  formato en uso tampoco puede cambiar de forma: las preguntas dejarían de
  encajar en su examen.
- Cambiar pesos, nombres o números de dominio no toca las preguntas, que
  apuntan al dominio por su id.
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.extensions import db
from app.models import Domain, Exam, FsrsParameters, Question, QuestionFormat, Skill, StudySession, User

ROW_KEY = re.compile(r"^(domain|format)-(\d+)-(\w+)$")
# «código — descripción», admitiendo también guion corto, guion medio o dos puntos.
SKILL_LINE = re.compile(r"^\s*(\S+?)\s*(?:—|–|-|:)\s+(.+?)\s*$")

EXAM_FIELDS = (
    "code", "name", "exam_date", "duration_minutes", "minutes_per_question",
    "pass_threshold_pct", "desired_retention_pct", "new_per_day",
)
DOMAIN_FIELDS = ("id", "number", "short_name", "name", "weight", "skills", "remove")
FORMAT_FIELDS = ("id", "option_count", "correct_count", "target_share_pct", "remove")


@dataclass
class ExamForm:
    """Lo que se pinta en el formulario: siempre texto, tal como lo escribió el usuario."""

    values: dict
    domains: list
    formats: list
    errors: list = field(default_factory=list)
    clean: dict = field(default_factory=dict)


def _pct(value):
    return "" if value is None else str(round(value * 100))


def empty_form():
    return ExamForm(
        values={
            "code": "", "name": "", "exam_date": "", "duration_minutes": "",
            "minutes_per_question": "2", "pass_threshold_pct": "70",
            "desired_retention_pct": "90", "new_per_day": "10",
        },
        domains=[{"id": "", "number": "1", "short_name": "", "name": "", "weight": "100", "skills": "", "remove": ""}],
        formats=[{"id": "", "option_count": "4", "correct_count": "1", "target_share_pct": "", "remove": ""}],
    )


def form_from_exam(exam):
    return ExamForm(
        values={
            "code": exam.code,
            "name": exam.name,
            "exam_date": exam.exam_date.isoformat() if exam.exam_date else "",
            "duration_minutes": "" if exam.duration_minutes is None else str(exam.duration_minutes),
            "minutes_per_question": str(exam.minutes_per_question),
            "pass_threshold_pct": str(exam.pass_threshold_pct),
            "desired_retention_pct": _pct(exam.desired_retention),
            "new_per_day": str(exam.new_per_day),
        },
        domains=[
            {
                "id": str(d.id), "number": str(d.number), "short_name": d.short_name, "name": d.name,
                "weight": str(d.weight), "remove": "",
                "skills": "\n".join(f"{s.code} — {s.description}" for s in d.skills),
            }
            for d in exam.domains
        ],
        formats=[
            {
                "id": str(f.id), "option_count": str(f.option_count), "correct_count": str(f.correct_count),
                "target_share_pct": _pct(f.target_share), "remove": "",
            }
            for f in exam.formats
        ],
    )


def parse_form(form):
    """Agrupa el formulario en datos del examen, filas de dominio y filas de formato."""
    rows = {"domain": defaultdict(dict), "format": defaultdict(dict)}
    for key, value in form.items():
        match = ROW_KEY.match(key)
        if match:
            kind, index, name = match.groups()
            rows[kind][int(index)][name] = value.strip() if name != "skills" else value

    def collect(kind, names):
        out = []
        for index in sorted(rows[kind]):
            row = {name: rows[kind][index].get(name, "") for name in names}
            row["remove"] = "1" if row["remove"] else ""
            # Una fila nueva que se dejó en blanco no es un error: se ignora.
            if not row["id"] and not any(row[n] for n in names if n not in ("id", "remove", "skills")):
                continue
            out.append(row)
        return out

    return ExamForm(
        values={name: form.get(name, "").strip() for name in EXAM_FIELDS},
        domains=collect("domain", DOMAIN_FIELDS),
        formats=collect("format", FORMAT_FIELDS),
    )


def _int(errors, raw, label, low, high, required=True):
    if raw in ("", None):
        if required:
            errors.append(f"Falta {label}.")
        return None
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{label[0].upper() + label[1:]} tiene que ser un número entero, y es «{raw}».")
        return None
    if not low <= value <= high:
        errors.append(f"{label[0].upper() + label[1:]} tiene que estar entre {low} y {high}, y es {value}.")
        return None
    return value


def _questions_shapes(exam):
    """{(opciones, correctas): nº de preguntas} y {domain_id: nº de preguntas} del examen."""
    shapes, per_domain = Counter(), Counter()
    if exam is None or exam.id is None:
        return shapes, per_domain
    for options, correct, domain_id in Question.query.filter_by(exam_id=exam.id).with_entities(
        Question.options, Question.correct, Question.domain_id
    ):
        shapes[(len(options), len(set(correct)))] += 1
        per_domain[domain_id] += 1
    return shapes, per_domain


def validate(form, exam=None):
    """Rellena form.errors y, si no hay ninguno, form.clean con los datos listos."""
    errors = form.errors
    v = form.values

    code = v["code"]
    if not code:
        errors.append("Falta el código del examen (por ejemplo, AIB-C01).")
    elif len(code) > 40:
        errors.append("El código del examen no puede pasar de 40 caracteres.")
    else:
        clash = Exam.query.filter(db.func.lower(Exam.code) == code.lower())
        if exam is not None and exam.id is not None:
            clash = clash.filter(Exam.id != exam.id)
        if clash.first() is not None:
            errors.append(f"Ya hay un examen con el código {code}. Elige otro.")
    if not v["name"]:
        errors.append("Falta el nombre del examen.")

    exam_date = None
    if v["exam_date"]:
        try:
            exam_date = date.fromisoformat(v["exam_date"])
        except ValueError:
            errors.append(f"La fecha del examen no es válida: «{v['exam_date']}». Usa el selector de fecha.")

    clean = {
        "code": code,
        "name": v["name"],
        "exam_date": exam_date,
        "duration_minutes": _int(errors, v["duration_minutes"], "la duración oficial", 1, 600, required=False),
        "minutes_per_question": _int(errors, v["minutes_per_question"], "los minutos por pregunta", 1, 30),
        "pass_threshold_pct": _int(errors, v["pass_threshold_pct"], "el umbral orientativo", 1, 100),
        "new_per_day": _int(errors, v["new_per_day"], "el cupo de nuevas al día", 0, 200),
    }
    retention = _int(errors, v["desired_retention_pct"], "la retención deseada", 70, 97)
    clean["desired_retention"] = None if retention is None else retention / 100

    shapes_in_use, questions_per_domain = _questions_shapes(exam)
    existing_domains = {d.id: d for d in exam.domains} if exam is not None and exam.id else {}
    existing_formats = {f.id: f for f in exam.formats} if exam is not None and exam.id else {}

    # Dominios
    kept_domains, removed_domains, numbers = [], [], Counter()
    for row in form.domains:
        domain = existing_domains.get(int(row["id"])) if row["id"].isdigit() else None
        if row["remove"]:
            if domain is not None:
                in_use = questions_per_domain.get(domain.id, 0)
                if in_use:
                    errors.append(
                        f"El dominio {domain.number} ({domain.short_name}) tiene {in_use} "
                        f"{'pregunta' if in_use == 1 else 'preguntas'} y no se puede quitar: "
                        "mientras las tenga, tiene que seguir en el examen."
                    )
                else:
                    removed_domains.append(domain)
            continue
        label = f"el dominio {row['number'] or '(sin número)'}"
        number = _int(errors, row["number"], f"el número de {label}", 1, 99)
        weight = _int(errors, row["weight"], f"el peso de {label}", 1, 100)
        if not row["short_name"]:
            errors.append(f"Falta el nombre corto de {label}: es el que sale en el medidor.")
        elif len(row["short_name"]) > 40:
            errors.append(f"El nombre corto de {label} no puede pasar de 40 caracteres.")
        if not row["name"]:
            errors.append(f"Falta el nombre de {label}.")
        skills, seen = [], set()
        for line_no, line in enumerate(row["skills"].splitlines(), start=1):
            if not line.strip():
                continue
            match = SKILL_LINE.match(line)
            if not match or len(match.group(1)) > 20:
                errors.append(
                    f"Habilidades de {label}, línea {line_no}: escribe «código — descripción», "
                    f"por ejemplo «1.1.1 — Explicar qué es un modelo fundacional». Ahora pone «{line.strip()}»."
                )
                continue
            skill_code, description = match.groups()
            if skill_code in seen:
                errors.append(f"Habilidades de {label}: el código {skill_code} está repetido.")
                continue
            seen.add(skill_code)
            skills.append((skill_code, description))
        if number is not None:
            numbers[number] += 1
        kept_domains.append({
            "domain": domain, "number": number, "short_name": row["short_name"], "name": row["name"],
            "weight": weight, "skills": skills,
        })
    if not kept_domains:
        errors.append("El examen necesita al menos un dominio.")
    for number, count in numbers.items():
        if count > 1:
            errors.append(f"El número de dominio {number} está repetido: cada dominio necesita el suyo.")
    weights = [d["weight"] for d in kept_domains]
    if kept_domains and None not in weights and sum(weights) != 100:
        total = sum(weights)
        gap = "faltan" if total < 100 else "sobran"
        errors.append(
            f"Los pesos de los dominios suman {total} %: {gap} {abs(100 - total)} "
            f"{'punto' if abs(100 - total) == 1 else 'puntos'} para llegar a 100."
        )

    # Formatos
    kept_formats, removed_formats, shapes = [], [], Counter()
    for row in form.formats:
        fmt = existing_formats.get(int(row["id"])) if row["id"].isdigit() else None
        old_shape = (fmt.option_count, fmt.correct_count) if fmt is not None else None
        in_use = shapes_in_use.get(old_shape, 0) if old_shape else 0
        if row["remove"]:
            if fmt is not None and in_use:
                errors.append(
                    f"El formato de {old_shape[0]} opciones con {old_shape[1]} "
                    f"{'correcta' if old_shape[1] == 1 else 'correctas'} lo usan {in_use} "
                    f"{'pregunta' if in_use == 1 else 'preguntas'} y no se puede quitar."
                )
            elif fmt is not None:
                removed_formats.append(fmt)
            continue
        options = _int(errors, row["option_count"], "el número de opciones de un formato", 2, 10)
        correct = _int(errors, row["correct_count"], "el número de correctas de un formato", 1, 9)
        if options is not None and correct is not None and correct >= options:
            errors.append(f"Un formato de {options} opciones necesita menos de {options} correctas.")
        if in_use and (options, correct) != old_shape:
            errors.append(
                f"El formato de {old_shape[0]} opciones con {old_shape[1]} "
                f"{'correcta' if old_shape[1] == 1 else 'correctas'} lo usan {in_use} "
                f"{'pregunta' if in_use == 1 else 'preguntas'}: no se puede cambiar, "
                "pero sí añadir otro formato al lado."
            )
        share = _int(errors, row["target_share_pct"], "la proporción objetivo de un formato", 0, 100, required=False)
        shapes[(options, correct)] += 1
        kept_formats.append({"format": fmt, "option_count": options, "correct_count": correct, "target_share": share})
    if not kept_formats:
        errors.append("El examen necesita al menos un formato de pregunta.")
    for (options, correct), count in shapes.items():
        if count > 1 and options is not None:
            errors.append(f"El formato de {options} opciones con {correct} correctas está repetido.")
    shares = [f["target_share"] for f in kept_formats]
    if shares and all(s is not None for s in shares) and sum(shares) != 100:
        errors.append(
            f"Las proporciones objetivo de los formatos suman {sum(shares)} %: "
            "tienen que sumar 100, o dejarse en blanco."
        )

    if not errors:
        clean.update(
            domains=kept_domains, removed_domains=removed_domains,
            formats=kept_formats, removed_formats=removed_formats,
        )
        form.clean = clean
    return not errors


def _renumber_safely(rows, key_obj, attrs):
    """Evita choques con las restricciones de unicidad al intercambiar valores.

    Postgres comprueba la unicidad fila a fila: cambiar el dominio 1 por el
    2 y el 2 por el 1 en la misma transacción choca a mitad. Primero se
    aparta cada fila que cambia a un valor negativo y luego se coloca.
    """
    moved = False
    for row in rows:
        obj = row[key_obj]
        if obj is not None and any(getattr(obj, a) != row[a] for a in attrs):
            setattr(obj, attrs[0], -obj.id)
            moved = True
    if moved:
        db.session.flush()


def apply(form, exam):
    """Guarda en `exam` (nuevo o existente) lo que validate() dejó en form.clean."""
    c = form.clean
    for name in ("code", "name", "exam_date", "duration_minutes", "minutes_per_question",
                 "pass_threshold_pct", "desired_retention", "new_per_day"):
        setattr(exam, name, c[name])
    if exam.id is None:
        db.session.add(exam)
    db.session.flush()

    for domain in c["removed_domains"]:
        Skill.query.filter_by(domain_id=domain.id).delete()
        db.session.delete(domain)
    for fmt in c["removed_formats"]:
        db.session.delete(fmt)
    db.session.flush()

    _renumber_safely(c["domains"], "domain", ("number",))
    for row in c["domains"]:
        domain = row["domain"] or Domain(exam_id=exam.id)
        domain.number, domain.short_name, domain.name, domain.weight = (
            row["number"], row["short_name"], row["name"], row["weight"]
        )
        if domain.id is None:
            db.session.add(domain)
            db.session.flush()
        # Las habilidades se reemplazan enteras: son una lista pegada a mano.
        Skill.query.filter_by(domain_id=domain.id).delete()
        for skill_code, description in row["skills"]:
            db.session.add(Skill(domain_id=domain.id, code=skill_code, description=description))

    _renumber_safely(c["formats"], "format", ("option_count", "correct_count"))
    for row in c["formats"]:
        fmt = row["format"] or QuestionFormat(exam_id=exam.id)
        fmt.option_count, fmt.correct_count = row["option_count"], row["correct_count"]
        fmt.target_share = None if row["target_share"] is None else row["target_share"] / 100
        if fmt.id is None:
            db.session.add(fmt)
    db.session.commit()
    db.session.expire(exam)
    return exam


def can_delete(exam):
    """Motivo por el que no se puede borrar, o None si se puede."""
    questions = Question.query.filter_by(exam_id=exam.id).count()
    sessions = StudySession.query.filter_by(exam_id=exam.id).count()
    if questions or sessions:
        return (
            f"{exam.code} tiene {questions} preguntas y {sessions} sesiones de estudio: "
            "no se puede borrar sin perderlas. Archívalo si ya no lo estudias."
        )
    return None


def delete(exam):
    User.query.filter_by(active_exam_id=exam.id).update({"active_exam_id": None})
    domain_ids = [d.id for d in exam.domains]
    if domain_ids:
        Skill.query.filter(Skill.domain_id.in_(domain_ids)).delete(synchronize_session=False)
    Domain.query.filter_by(exam_id=exam.id).delete()
    QuestionFormat.query.filter_by(exam_id=exam.id).delete()
    FsrsParameters.query.filter_by(exam_id=exam.id).delete()
    db.session.delete(exam)
    db.session.commit()
