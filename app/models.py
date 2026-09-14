from datetime import datetime, timezone

from flask_login import UserMixin

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    """Un único registro, sembrado desde el entorno. Ver app/cli.py."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    ext_id = db.Column(db.String(40), unique=True, nullable=False, index=True)
    domain = db.Column(db.Integer, nullable=False)  # 1 a 4
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

    attempts = db.relationship("Attempt", back_populates="question")


class StudySession(db.Model):
    __tablename__ = "study_sessions"

    id = db.Column(db.Integer, primary_key=True)
    mode = db.Column(db.String(20), nullable=False)  # simulacro | rapida | dominio | fallos
    domain = db.Column(db.Integer, nullable=True)  # solo relevante en modo "dominio"
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

    question = db.relationship("Question", back_populates="attempts")
    session = db.relationship("StudySession", back_populates="attempts")
