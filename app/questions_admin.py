"""Utilidad de carga de preguntas: vista web con vista previa obligatoria.

El mismo validador (app.import_validation) lo usa el comando de consola
en app/cli.py, para poder sembrar y hacer copias de seguridad sin
navegador.
"""
import json

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.extensions import db
from app.import_validation import question_to_short_format, validate_import
from app.models import Question

bp = Blueprint("questions_admin", __name__, url_prefix="/preguntas")


@bp.route("/", methods=["GET"])
@login_required
def index():
    total = Question.query.filter_by(active=True).count()
    return render_template("import.html", total=total)


@bp.route("/preview", methods=["POST"])
@login_required
def preview():
    """Vista previa obligatoria: qué entra, qué se descarta y por qué."""
    payload = request.get_json(silent=True) or {}
    raw_text = payload.get("raw", "")
    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return jsonify(error=f"JSON inválido: {exc}"), 400

    result = validate_import(items)
    return jsonify(
        accepted=result.accepted,
        rejected=[{"identifier": ident, "reason": reason} for ident, reason in result.rejected],
    )


@bp.route("/confirm", methods=["POST"])
@login_required
def confirm():
    """Inserta las preguntas ya validadas por /preview. Vuelve a validar por si
    la base cambió entre la vista previa y la confirmación (idempotencia)."""
    payload = request.get_json(silent=True) or {}
    raw_text = payload.get("raw", "")
    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return jsonify(error=f"JSON inválido: {exc}"), 400

    result = validate_import(items)
    for item in result.accepted:
        db.session.add(Question(**item))
    db.session.commit()

    return jsonify(
        inserted=len(result.accepted),
        rejected=[{"identifier": ident, "reason": reason} for ident, reason in result.rejected],
    )


@bp.route("/exportar", methods=["GET"])
@login_required
def export():
    questions = Question.query.filter_by(active=True).order_by(Question.ext_id).all()
    data = [question_to_short_format(q) for q in questions]
    response = jsonify(data)
    response.headers["Content-Disposition"] = "attachment; filename=questions.export.json"
    return response
