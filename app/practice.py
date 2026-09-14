"""Vistas de página: inicio, sesión de práctica, historial."""
from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Question, StudySession
from app.sampling import DOMAIN_NAMES, DOMAIN_WEIGHTS, PASS_THRESHOLD_PCT, domain_readiness

bp = Blueprint("practice", __name__)


@bp.route("/")
@login_required
def home():
    readiness = {d: domain_readiness(d) for d in DOMAIN_WEIGHTS}
    question_counts = {
        d: Question.query.filter_by(active=True, domain=d).count() for d in DOMAIN_WEIGHTS
    }
    total_questions = sum(question_counts.values())
    failed_count = (
        Question.query.join(Question.attempts)
        .filter_by(is_correct=False)
        .distinct()
        .count()
    )
    history = (
        StudySession.query.filter(StudySession.finished_at.isnot(None))
        .order_by(StudySession.finished_at.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "home.html",
        readiness=readiness,
        domain_names=DOMAIN_NAMES,
        domain_weights=DOMAIN_WEIGHTS,
        question_counts=question_counts,
        total_questions=total_questions,
        failed_count=failed_count,
        history=history,
        pass_threshold=PASS_THRESHOLD_PCT,
    )


@bp.route("/tanda")
@login_required
def session_view():
    return render_template("session.html")
