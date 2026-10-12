"""Evaluación del algoritmo (issue #22)."""
import json
import math
from datetime import timedelta

import pytest
from fsrs.scheduler import DEFAULT_PARAMETERS

from app.evaluation import ReplayConfigError, evaluate, load_parameters, replay
from app.extensions import db
from app.models import Attempt, Exam, FsrsParameters, Question, StudySession
from tests.test_metricas import AHORA, CODIGO, con_respuestas, examen  # noqa: F401  (fixtures)


def test_las_metricas_de_unas_predicciones_conocidas():
    m = evaluate([(0.9, 1), (0.9, 0), (0.5, 1), (0.5, 0)])
    assert m["log_loss"] == pytest.approx(-(math.log(0.9) + math.log(0.1) + 2 * math.log(0.5)) / 4)
    assert m["baseline_log_loss"] == pytest.approx(math.log(2)), "predecir siempre el 50 %"
    # Tramo 50-60: 50 % predicho y 50 % real. Tramo 90-100: 90 % frente a 50 %.
    assert [(c["low"], c["count"], c["actual"]) for c in m["calibration"]] == [(50, 2, 0.5), (90, 2, 0.5)]
    assert m["rmse_bins"] == pytest.approx(math.sqrt(2 * 0.4 ** 2 / 4))
    assert (m["predicted"], m["actual"], m["reliable"]) == (pytest.approx(0.7), 0.5, False)


def test_un_cien_por_cien_fallado_no_rompe_el_log_loss():
    m = evaluate([(1.0, 0)])
    assert math.isfinite(m["log_loss"])
    assert m["calibration"][0]["low"] == 90, "el 100 % cae en el último tramo"


def test_sin_revisiones_no_hay_metricas():
    assert evaluate([]) is None


@pytest.mark.parametrize(
    "contenido, mensaje",
    [
        ([1, 2], "necesita 21 parámetros y el fichero trae 2"),
        ({"pesos": []}, "una lista de números"),
        (["a"] * 21, "una lista de números"),
    ],
)
def test_parametros_que_no_valen(contenido, mensaje):
    with pytest.raises(ReplayConfigError, match=mensaje):
        load_parameters(contenido)


def test_parametros_que_si_valen():
    assert load_parameters(list(DEFAULT_PARAMETERS)) == list(DEFAULT_PARAMETERS)
    assert load_parameters({"parameters": list(DEFAULT_PARAMETERS)}) == list(DEFAULT_PARAMETERS)


def test_la_repeticion_aparta_lo_de_menos_de_un_dia(app, con_respuestas):
    with app.app_context():
        exam = db.session.get(Exam, con_respuestas)
        antes = replay(exam, now=AHORA)
        # m1 se respondió hace 3, 1 y 0 días; m2, hace 2 y 1: tres revisiones con predicción.
        assert (antes["metrics"]["reviews"], antes["same_day"], antes["first_seen"]) == (3, 0, 4)

        m3 = Question.query.filter_by(exam_id=exam.id, ext_id="m3").one()
        primera = Attempt.query.filter_by(question_id=m3.id).one()
        db.session.add(Attempt(question_id=m3.id, session_id=primera.session_id, selected=[0], is_correct=True,
                               seconds_spent=30, answered_at=primera.answered_at + timedelta(hours=2)))
        db.session.commit()
        despues = replay(exam, now=AHORA)
    assert despues["same_day"] == 1 and despues["metrics"]["reviews"] == 3


def test_la_retencion_cambia_la_carga_y_no_las_predicciones(app, con_respuestas):
    with app.app_context():
        exam = db.session.get(Exam, con_respuestas)
        vigente = replay(exam, now=AHORA)
        baja = replay(exam, desired_retention=0.7, now=AHORA)
        with pytest.raises(ReplayConfigError, match="entre 0.70 y 0.97"):
            replay(exam, desired_retention=0.99)
    assert baja["metrics"]["log_loss"] == pytest.approx(vigente["metrics"]["log_loss"])
    assert baja["due"][30] <= vigente["due"][30], "con menos retención los repasos se espacian más"


def test_otros_umbrales_recalculan_las_notas(app, con_respuestas):
    """La primera respuesta a m1 (20 s, segura) es Easy con la referencia de 60 s. Con fast_factor 0
    nada es rápido: pasa a Good, su estabilidad baja y cambian las predicciones siguientes."""
    with app.app_context():
        exam = db.session.get(Exam, con_respuestas)
        vigente = replay(exam, now=AHORA)
        otra = replay(exam, rating_overrides={"fast_factor": 0.0}, now=AHORA)
    assert otra["rating_config"]["fast_factor"] == 0.0
    assert otra["metrics"]["predicted"] != pytest.approx(vigente["metrics"]["predicted"])


def test_el_comando_compara_con_la_vigente(app, con_respuestas, tmp_path):
    runner = app.test_cli_runner()
    fichero = tmp_path / "pesos.json"
    fichero.write_text(json.dumps({"parameters": list(DEFAULT_PARAMETERS)}), encoding="utf-8")
    salida = runner.invoke(args=["fsrs", "replay", "--exam", CODIGO.lower(), "--params", str(fichero),
                                 "--desired-retention", "0.8", "--slow-factor", "2"])
    assert salida.exit_code == 0, salida.output
    assert "Vigente" in salida.output and "Propuesta" in salida.output
    assert "80.0 %" in salida.output and "Calibración · Propuesta" in salida.output
    with app.app_context():
        assert FsrsParameters.query.filter_by(exam_id=con_respuestas).count() == 1, "no guarda nada"

    for argumentos, mensaje in (
        (["--exam", "NO-EXISTE"], "No hay ningún examen con el código NO-EXISTE"),
        (["--exam", CODIGO, "--desired-retention", "0.99"], "entre 0.70 y 0.97"),
    ):
        salida = runner.invoke(args=["fsrs", "replay", *argumentos])
        assert salida.exit_code != 0 and mensaje in salida.output


def test_el_panel_muestra_el_algoritmo(app, logged_in, con_respuestas):
    logged_in.post(f"/examen/{con_respuestas}/estudiar")
    try:
        html = logged_in.get("/metricas").get_data(as_text=True)
    finally:
        logged_in.post("/examen/volver-al-activo")
    assert "El algoritmo" in html and "Log loss" in html and "RMSE por tramos" in html
    assert "3 revisiones evaluadas" in html
    assert "Parámetros de fábrica" in html


def test_sin_revisiones_repetidas_el_panel_lo_explica(app, logged_in, examen):
    with app.app_context():
        q = Question.query.filter_by(exam_id=examen, ext_id="m1").one()
        sesion = StudySession(exam_id=examen, mode="rapida", question_count=1)
        db.session.add(sesion)
        db.session.flush()
        db.session.add(Attempt(question_id=q.id, session_id=sesion.id, selected=[0], is_correct=True,
                               seconds_spent=30, answered_at=AHORA))
        db.session.commit()
    logged_in.post(f"/examen/{examen}/estudiar")
    try:
        html = logged_in.get("/metricas").get_data(as_text=True)
    finally:
        logged_in.post("/examen/volver-al-activo")
    assert "Aún no hay revisiones que evaluar" in html
