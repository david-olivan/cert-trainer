"""Kit para generar preguntas e importación por examen (issue #20)."""
import json

import pytest

from app.extensions import db
from app.kit import build_kit, largest_remainder, next_ids, suggested_split, coverage
from app.models import Domain, Exam, FsrsParameters, Question, QuestionFormat, Skill


@pytest.mark.parametrize(
    "total, pesos, esperado",
    [
        (20, {1: 24, 2: 28, 3: 24, 4: 24}, {1: 5, 2: 5, 3: 5, 4: 5}),
        # 2,4 / 2,8 / 2,4 / 2,4: el resto mayor (0,8) se lleva el primero de los
        # dos sobrantes, y a igualdad de resto gana el primero en orden.
        (10, {1: 24, 2: 28, 3: 24, 4: 24}, {1: 3, 2: 3, 3: 2, 4: 2}),
        (7, {"a": 1, "b": 1}, {"a": 4, "b": 3}),
        (0, {1: 50, 2: 50}, {1: 0, 2: 0}),
    ],
)
def test_el_reparto_no_pierde_preguntas(total, pesos, esperado):
    reparto = largest_remainder(total, pesos)
    assert sum(reparto.values()) == total
    assert reparto == esperado


def test_el_kit_de_aib_lleva_todo_lo_necesario(app):
    with app.app_context():
        exam = Exam.query.filter_by(code="AIB-C01").one()
        md = build_kit(exam, 20)
    assert "Genera **20 preguntas nuevas**" in md
    for nombre in ("Conceptos básicos y alfabetización en IA", "Gobernanza de la IA y liderazgo responsable"):
        assert nombre in md
    assert "| 2 | Estrategia de IA y creación de valor empresarial | 28 % | 12 |" in md
    assert "| 5 opciones con 2 correctas | 17 % | 4 |" in md
    # El banco sembrado tiene 4 múltiples de 44 (9 %), por debajo del 17 %.
    assert "Formato de 5 opciones con 2 correctas: 9 % del banco, por debajo del 17 % objetivo" in md
    assert '"exam": "AIB-C01"' in md
    assert "Siguientes `id` libres por dominio: d1-12, d2-13, d3-11, d4-12." in md
    assert "d1-01, d1-02" in md


def test_el_reparto_por_formato_cubre_el_deficit(app):
    with app.app_context():
        exam = Exam.query.filter_by(code="AIB-C01").one()
        por_dominio, por_formato = suggested_split(exam, 20, coverage(exam))
    assert sum(por_dominio.values()) == 20
    assert por_formato == {(4, 1): 13, (5, 2): 7}


@pytest.fixture
def examen_con_habilidades(app):
    with app.app_context():
        exam = Exam(code="KIT-1", name="Examen del kit", pass_threshold_pct=70, minutes_per_question=1)
        db.session.add(exam)
        db.session.flush()
        d1 = Domain(exam_id=exam.id, number=1, name="Primero", short_name="Uno", weight=70)
        d2 = Domain(exam_id=exam.id, number=2, name="Segundo", short_name="Dos", weight=30)
        db.session.add_all([d1, d2])
        db.session.add(QuestionFormat(exam_id=exam.id, option_count=3, correct_count=1))
        db.session.flush()
        db.session.add_all([
            Skill(domain_id=d1.id, code="1.1", description="Cubierta dos veces"),
            Skill(domain_id=d1.id, code="1.2", description="Sin preguntas"),
            Skill(domain_id=d2.id, code="2.1", description="Cubierta una vez"),
        ])
        for ext_id, dom, hab in (("d1-01", d1, "1.1"), ("d1-07", d1, "1.1"), ("d2-03", d2, "2.1")):
            db.session.add(Question(exam_id=exam.id, domain_id=dom.id, ext_id=ext_id, skill=hab, type="s",
                                    stem="x", options=["a", "b", "c"], correct=[0], explanation="y"))
        db.session.commit()
        exam_id = exam.id
    yield exam_id
    with app.app_context():
        Question.query.filter_by(exam_id=exam_id).delete()
        for d in Domain.query.filter_by(exam_id=exam_id):
            Skill.query.filter_by(domain_id=d.id).delete()
        Domain.query.filter_by(exam_id=exam_id).delete()
        QuestionFormat.query.filter_by(exam_id=exam_id).delete()
        FsrsParameters.query.filter_by(exam_id=exam_id).delete()
        db.session.delete(db.session.get(Exam, exam_id))
        db.session.commit()


def test_el_kit_senala_las_habilidades_sin_cubrir(app, examen_con_habilidades):
    with app.app_context():
        exam = db.session.get(Exam, examen_con_habilidades)
        md = build_kit(exam, 10)
        assert next_ids(exam) == {1: "d1-08", 2: "d2-04"}
    assert "- 1.1 — Cubierta dos veces (2)" in md
    assert "Habilidades sin ninguna pregunta: 1.2." in md
    assert "Habilidades con una sola pregunta: 2.1." in md
    assert "Dominio 1 (Uno): 7 preguntas." in md and "Dominio 2 (Dos): 3 preguntas." in md
    assert "Por formato" not in md, "sin proporción objetivo no se sugiere reparto por formato"


def test_la_pagina_y_la_descarga_del_kit(app, logged_in):
    with app.app_context():
        exam_id = Exam.query.filter_by(code="AIB-C01").one().id
    html = logged_in.get(f"/examenes/{exam_id}/kit?n=12").get_data(as_text=True)
    assert "Genera **12 preguntas nuevas**" in html
    assert "Copiar" in html and "Descargar .md" in html

    descarga = logged_in.get(f"/examenes/{exam_id}/kit.md?n=500")
    assert descarga.mimetype == "text/markdown"
    assert "kit-aib-c01.md" in descarga.headers["Content-Disposition"]
    assert "Genera **100 preguntas nuevas**" in descarga.get_data(as_text=True), "se acota al máximo"


def _bloque(code, ext_id="k-01", dom=1):
    return json.dumps({"exam": code, "questions": [{
        "id": ext_id, "dom": dom, "hab": "1.1", "q": "Enunciado", "o": ["a", "b", "c"], "ok": [0], "w": "Porque sí",
    }]})


def test_un_bloque_con_codigo_entra_en_su_examen(app, logged_in, examen_con_habilidades):
    vista = logged_in.post("/preguntas/preview", json={"raw": _bloque("kit-1")}).get_json()
    assert vista["exam"] == "KIT-1"
    assert [q["ext_id"] for q in vista["accepted"]] == ["k-01"]

    hecho = logged_in.post("/preguntas/confirm", json={"raw": _bloque("KIT-1")}).get_json()
    assert hecho == {"exam": "KIT-1", "inserted": 1, "rejected": []}
    with app.app_context():
        assert Question.query.filter_by(exam_id=examen_con_habilidades, ext_id="k-01").count() == 1
        assert Question.query.filter_by(ext_id="k-01").count() == 1, "no entra en el examen en curso"


@pytest.mark.parametrize(
    "bloque, mensaje",
    [
        (json.dumps({"exam": "NO-EXISTE", "questions": []}), "No hay ningún examen con el código NO-EXISTE"),
        (json.dumps({"questions": []}), "no dice a qué examen van"),
        (json.dumps({"exam": "AIB-C01", "questions": {}}), "tiene que ser una lista"),
        (json.dumps({"preguntas": []}), "No se reconoce el formato"),
    ],
)
def test_un_bloque_mal_formado_se_rechaza_entero(logged_in, bloque, mensaje):
    for ruta in ("/preguntas/preview", "/preguntas/confirm"):
        respuesta = logged_in.post(ruta, json={"raw": bloque})
        assert respuesta.status_code == 400
        assert mensaje in respuesta.get_json()["error"]


def test_la_consola_importa_un_bloque_con_codigo(app, examen_con_habilidades, tmp_path):
    fichero = tmp_path / "bloque.json"
    fichero.write_text(_bloque("KIT-1", ext_id="k-cli", dom=2), encoding="utf-8")
    resultado = app.test_cli_runner().invoke(args=["questions", "import", str(fichero)])
    assert resultado.exit_code == 0, resultado.output
    assert "Insertadas 1 preguntas en KIT-1." in resultado.output

    fichero.write_text(json.dumps({"exam": "NO-EXISTE", "questions": []}), encoding="utf-8")
    resultado = app.test_cli_runner().invoke(args=["questions", "import", str(fichero)])
    assert resultado.exit_code != 0
    assert "No hay ningún examen con el código NO-EXISTE" in resultado.output
