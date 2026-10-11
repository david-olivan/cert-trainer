from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import false

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    """Un único registro, sembrado desde el entorno. Ver app/cli.py."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Modo «primero piensa» (issue #14): enunciado antes que opciones. Vive
    # en el servidor para que valga igual en el móvil y en el portátil.
    recall_first = db.Column(db.Boolean, nullable=False, default=False, server_default=false())


class Exam(db.Model):
    """Un examen que se prepara: AIB-C01 es el primero (issue #7).

    Hasta que exista el examen activo (#8), la aplicación trabaja sobre el
    primero sin archivar: ver app/exams.py.
    """

    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    exam_date = db.Column(db.Date, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)  # duración oficial, informativa
    minutes_per_question = db.Column(db.Integer, nullable=False, default=2)
    pass_threshold_pct = db.Column(db.Integer, nullable=False)  # orientativo, nunca predicción
    desired_retention = db.Column(db.Float, nullable=False, default=0.9)  # para FSRS (#16)
    archived = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    domains = db.relationship("Domain", back_populates="exam", order_by="Domain.number")
    formats = db.relationship("QuestionFormat", back_populates="exam", order_by="QuestionFormat.option_count")


class Domain(db.Model):
    __tablename__ = "domains"
    __table_args__ = (db.UniqueConstraint("exam_id", "number", name="uq_domains_exam_number"),)

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", name="fk_domains_exam"), nullable=False)
    number = db.Column(db.Integer, nullable=False)  # el que usa la guía oficial: 1, 2, 3…
    name = db.Column(db.String(200), nullable=False)
    short_name = db.Column(db.String(40), nullable=False)
    weight = db.Column(db.Integer, nullable=False)  # porcentaje; los de un examen suman 100

    exam = db.relationship("Exam", back_populates="domains")
    skills = db.relationship("Skill", back_populates="domain", order_by="Skill.code")


class Skill(db.Model):
    """Habilidad de la guía oficial. Opcional: la usan la cobertura y el kit (#20).

    Question.skill sigue siendo el código en texto, sin clave ajena: las
    preguntas pueden citar habilidades que todavía no se han dado de alta.
    """

    __tablename__ = "skills"
    __table_args__ = (db.UniqueConstraint("domain_id", "code", name="uq_skills_domain_code"),)

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey("domains.id", name="fk_skills_domain"), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=False)

    domain = db.relationship("Domain", back_populates="skills")


class QuestionFormat(db.Model):
    """Formato de pregunta que admite un examen: cuántas opciones y cuántas correctas.

    Una pregunta no apunta a su formato: se deduce de len(options) y
    len(correct), y el validador comprueba que el examen lo admita.
    """

    __tablename__ = "question_formats"
    __table_args__ = (
        db.UniqueConstraint("exam_id", "option_count", "correct_count", name="uq_question_formats_exam_shape"),
    )

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", name="fk_question_formats_exam"), nullable=False)
    option_count = db.Column(db.Integer, nullable=False)
    correct_count = db.Column(db.Integer, nullable=False)
    target_share = db.Column(db.Float, nullable=True)  # proporción objetivo en el banco, 0-1

    exam = db.relationship("Exam", back_populates="formats")


class Question(db.Model):
    __tablename__ = "questions"
    # ext_id es único dentro de cada examen, no en todo el banco: dos
    # exámenes pueden numerar sus preguntas igual.
    __table_args__ = (db.UniqueConstraint("exam_id", "ext_id", name="uq_questions_exam_ext_id"),)

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", name="fk_questions_exam"), nullable=False, index=True)
    domain_id = db.Column(db.Integer, db.ForeignKey("domains.id", name="fk_questions_domain"), nullable=False)
    ext_id = db.Column(db.String(40), nullable=False, index=True)
    skill = db.Column(db.String(20), nullable=False)  # código de la guía, ej. "2.1.3"
    type = db.Column(db.String(1), nullable=False)  # "s" única, "m" múltiple
    stem = db.Column(db.Text, nullable=False)
    options = db.Column(db.JSON, nullable=False)  # lista de strings
    correct = db.Column(db.JSON, nullable=False)  # lista de índices base 0
    explanation = db.Column(db.Text, nullable=False)
    hint = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    source = db.Column(db.String(10), nullable=False, default="seed")  # "seed" | "import"
    active = db.Column(db.Boolean, nullable=False, default=True)

    exam = db.relationship("Exam")
    domain = db.relationship("Domain")
    attempts = db.relationship("Attempt", back_populates="question")


class StudySession(db.Model):
    __tablename__ = "study_sessions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", name="fk_study_sessions_exam"), nullable=False)
    mode = db.Column(db.String(20), nullable=False)  # simulacro | rapida | dominio | fallos
    domain = db.Column(db.Integer, nullable=True)  # número de dominio, solo en modo "dominio"
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    question_count = db.Column(db.Integer, nullable=False, default=0)
    score_pct = db.Column(db.Integer, nullable=True)

    attempts = db.relationship("Attempt", back_populates="session", order_by="Attempt.answered_at")


class Attempt(db.Model):
    """Un registro por pregunta respondida. Sostiene toda la analítica: no simplificar."""

    __tablename__ = "attempts"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("study_sessions.id"), nullable=False)
    selected = db.Column(db.JSON, nullable=False)  # índices seleccionados por el usuario
    is_correct = db.Column(db.Boolean, nullable=False)
    seconds_spent = db.Column(db.Integer, nullable=True)
    answered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    # Señales para la repetición espaciada (issue #13). Nulas en los
    # intentos anteriores a que existieran: no se inventan.
    confidence = db.Column(db.String(10), nullable=True)  # "sure" | "unsure"
    hint_used = db.Column(db.Boolean, nullable=True)  # se pidió la pista antes de responder
    # Permutación mostrada: option_order[i] es el índice original de la
    # opción que apareció en la posición i. Permite medir el sesgo de
    # posición; `selected` sigue guardándose en índices originales.
    option_order = db.Column(db.JSON, nullable=True)
    # Modo «primero piensa» (issue #14). recall_first lo decide el servidor
    # al empezar la tanda; seconds_to_reveal es lo que se tardó en pedir las
    # opciones, contado desde que apareció el enunciado. Nulos en los
    # intentos anteriores.
    recall_first = db.Column(db.Boolean, nullable=True)
    seconds_to_reveal = db.Column(db.Integer, nullable=True)
    # Repetición espaciada (issue #16). rating es la nota FSRS (1 Again,
    # 2 Hard, 3 Good, 4 Easy) que se dedujo de la respuesta; predicted_r, la
    # probabilidad de acierto que FSRS daba justo antes de responder. Nula
    # si la pregunta no se había visto nunca: no había predicción que medir.
    rating = db.Column(db.Integer, nullable=True)
    predicted_r = db.Column(db.Float, nullable=True)

    question = db.relationship("Question", back_populates="attempts")
    session = db.relationship("StudySession", back_populates="attempts")


class ReviewState(db.Model):
    """Estado FSRS de una pregunta: cuándo toca repasarla y cuánto se recuerda.

    Es derivable: `flask fsrs rebuild` lo reconstruye entero a partir de
    Attempt, que es el registro de revisiones. Ver app/srs.py.
    """

    __tablename__ = "review_states"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer, db.ForeignKey("questions.id", name="fk_review_states_question"), nullable=False, unique=True
    )
    state = db.Column(db.Integer, nullable=False)  # fsrs.State: 1 Learning, 2 Review, 3 Relearning
    step = db.Column(db.Integer, nullable=True)
    stability = db.Column(db.Float, nullable=True)
    difficulty = db.Column(db.Float, nullable=True)
    due = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    last_review = db.Column(db.DateTime(timezone=True), nullable=True)

    question = db.relationship("Question")


class FsrsParameters(db.Model):
    """Parámetros de FSRS de un examen, con su historial.

    Una fila activa por examen. Las que deje el optimizador (#23) se
    guardan aunque no se activen, con sus métricas, para comparar ajustes.
    La retención deseada no vive aquí sino en Exam: es una decisión del
    usuario, no un resultado del ajuste.
    """

    __tablename__ = "fsrs_parameters"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", name="fk_fsrs_parameters_exam"), nullable=False)
    parameters = db.Column(db.JSON, nullable=False)  # los 21 pesos del modelo
    rating_config = db.Column(db.JSON, nullable=False)  # umbrales para deducir la nota: ver app/srs.py
    source = db.Column(db.String(20), nullable=False)  # "default" | "optimizer"
    review_count = db.Column(db.Integer, nullable=False, default=0)  # revisiones con que se ajustó
    metrics = db.Column(db.JSON, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
