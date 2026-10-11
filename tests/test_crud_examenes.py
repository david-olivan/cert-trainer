"""Gestión de exámenes (issue #19)."""
import pytest

from app.extensions import db
from app.models import Domain, Exam, Question, QuestionFormat, Skill


def _datos(code="NUEVO-1", dominios=None, formatos=None, **extra):
    """Un formulario como lo envía el navegador."""
    form = {
        "code": code, "name": "Examen de prueba", "exam_date": "2027-01-20", "duration_minutes": "90",
        "minutes_per_question": "2", "pass_threshold_pct": "70", "desired_retention_pct": "90",
        "new_per_day": "8",
    }
    form.update(extra)
    dominios = dominios if dominios is not None else [
        {"number": "1", "short_name": "Uno", "name": "Dominio uno", "weight": "60",
         "skills": "1.1 — Primera habilidad\n1.2 - Segunda habilidad"},
        {"number": "2", "short_name": "Dos", "name": "Dominio dos", "weight": "40"},
    ]
    formatos = formatos if formatos is not None else [
        {"option_count": "4", "correct_count": "1", "target_share_pct": "80"},
        {"option_count": "5", "correct_count": "2", "target_share_pct": "20"},
    ]
    for i, d in enumerate(dominios):
        for k, v in d.items():
            form[f"domain-{i}-{k}"] = v
    for i, f in enumerate(formatos):
        for k, v in f.items():
            form[f"format-{i}-{k}"] = v
    return form


@pytest.fixture
def limpiar(app):
    """Borra los exámenes creados en la prueba y deja AIB-C01 sin archivar."""
    yield
    with app.app_context():
        for exam in Exam.query.filter(Exam.code != "AIB-C01").all():
            Question.query.filter_by(exam_id=exam.id).delete()
            for d in exam.domains:
                Skill.query.filter_by(domain_id=d.id).delete()
            Domain.query.filter_by(exam_id=exam.id).delete()
            QuestionFormat.query.filter_by(exam_id=exam.id).delete()
            db.session.delete(exam)
        Exam.query.filter_by(code="AIB-C01").one().archived = False
        db.session.commit()


def _examen(app, code):
    with app.app_context():
        exam = Exam.query.filter_by(code=code).one()
        datos = {
            "id": exam.id, "new_per_day": exam.new_per_day, "desired_retention": exam.desired_retention,
            "domains": [(d.id, d.number, d.short_name, d.weight, [(s.code, s.description) for s in d.skills])
                        for d in exam.domains],
            "formats": [(f.id, f.option_count, f.correct_count, f.target_share) for f in exam.formats],
        }
        return datos


def test_la_lista_marca_el_examen_en_curso(logged_in):
    html = logged_in.get("/examenes/").get_data(as_text=True)
    assert "AIB-C01 · en curso" in html
    assert "Nuevo examen" in html


def test_crear_un_examen(app, logged_in, limpiar):
    respuesta = logged_in.post("/examenes/nuevo", data=_datos())
    assert respuesta.status_code == 302, respuesta.get_data(as_text=True)[:2000]
    e = _examen(app, "NUEVO-1")
    assert e["new_per_day"] == 8 and e["desired_retention"] == pytest.approx(0.9)
    assert [(n, s, w) for _id, n, s, w, _sk in e["domains"]] == [(1, "Uno", 60), (2, "Dos", 40)]
    assert e["domains"][0][4] == [("1.1", "Primera habilidad"), ("1.2", "Segunda habilidad")]
    assert [(o, c, round(t, 2)) for _id, o, c, t in e["formats"]] == [(4, 1, 0.8), (5, 2, 0.2)]


@pytest.mark.parametrize(
    "cambios, mensaje",
    [
        ({"domain-1-weight": "36"}, "suman 96 %: faltan 4 puntos"),
        ({"domain-1-weight": "45"}, "suman 105 %: sobran 5 puntos"),
        ({"domain-1-number": "1"}, "El número de dominio 1 está repetido"),
        ({"code": "aib-c01"}, "Ya hay un examen con el código aib-c01"),
        ({"format-1-correct_count": "5"}, "necesita menos de 5 correctas"),
        ({"format-1-target_share_pct": "30"}, "suman 110 %"),
        ({"domain-0-skills": "esto no lleva separador"}, "línea 1: escribe «código — descripción»"),
        ({"desired_retention_pct": "99"}, "entre 70 y 97"),
        ({"exam_date": "mañana"}, "La fecha del examen no es válida"),
    ],
)
def test_un_formulario_mal_rellenado_no_guarda_nada_y_dice_por_que(app, logged_in, limpiar, cambios, mensaje):
    respuesta = logged_in.post("/examenes/nuevo", data=_datos(**{}) | cambios)
    assert respuesta.status_code == 400
    html = respuesta.get_data(as_text=True)
    assert "No se ha guardado nada" in html
    assert mensaje in html
    with app.app_context():
        assert Exam.query.filter_by(code="NUEVO-1").first() is None


def test_editar_aib_no_toca_sus_preguntas(app, logged_in, limpiar):
    antes = _examen(app, "AIB-C01")
    with app.app_context():
        aib = db.session.get(Exam, antes["id"])
        datos_aib = {
            "name": aib.name, "exam_date": aib.exam_date.isoformat() if aib.exam_date else "",
            "duration_minutes": str(aib.duration_minutes or ""), "minutes_per_question": str(aib.minutes_per_question),
            "pass_threshold_pct": str(aib.pass_threshold_pct),
        }
        nombres = {d.id: d.name for d in aib.domains}
        dominio_de = {q.id: q.domain_id for q in Question.query.all()}

    assert logged_in.get(f"/examenes/{antes['id']}").status_code == 200
    dominios = [{"id": str(i), "number": str(n), "short_name": s, "name": nombres[i], "weight": str(w)}
                for i, n, s, w, _sk in antes["domains"]]
    dominios[0]["weight"], dominios[1]["weight"] = "28", "24"  # se intercambian dos pesos: siguen sumando 100
    formatos = [{"id": str(i), "option_count": str(o), "correct_count": str(c), "target_share_pct": str(round(t * 100))}
                for i, o, c, t in antes["formats"]]
    formatos[0]["target_share_pct"], formatos[1]["target_share_pct"] = "83", "17"
    try:
        respuesta = logged_in.post(f"/examenes/{antes['id']}", data=_datos(
            code="AIB-C01", dominios=dominios, formatos=formatos, new_per_day="15", **datos_aib))
        assert respuesta.status_code == 302, respuesta.get_data(as_text=True)[:2000]
        despues = _examen(app, "AIB-C01")
        assert despues["new_per_day"] == 15
        assert [w for *_x, w, _sk in despues["domains"]] == [28, 24, 24, 24]
        with app.app_context():
            assert {q.id: q.domain_id for q in Question.query.all()} == dominio_de
    finally:
        # Se deshace solo lo que la prueba cambió.
        with app.app_context():
            db.session.get(Exam, antes["id"]).new_per_day = antes["new_per_day"]
            for (i, _n, _s, w, _sk) in antes["domains"]:
                db.session.get(Domain, i).weight = w
            for (i, _o, _c, t) in antes["formats"]:
                db.session.get(QuestionFormat, i).target_share = t
            db.session.commit()
        assert _examen(app, "AIB-C01") == antes


def test_no_se_quita_un_dominio_ni_un_formato_con_preguntas(app, logged_in):
    antes = _examen(app, "AIB-C01")
    dominios = [{"id": str(i), "number": str(n), "short_name": s, "name": "x", "weight": str(w)}
                for i, n, s, w, _sk in antes["domains"]]
    formatos = [{"id": str(i), "option_count": str(o), "correct_count": str(c), "target_share_pct": ""}
                for i, o, c, _t in antes["formats"]]

    quitar_dominio = [dict(d) for d in dominios]
    quitar_dominio[2]["remove"] = "1"
    html = logged_in.post(f"/examenes/{antes['id']}", data=_datos(
        code="AIB-C01", dominios=quitar_dominio, formatos=formatos)).get_data(as_text=True)
    assert "El dominio 3 (Gobernanza) tiene 10 preguntas y no se puede quitar" in html

    quitar_formato = [dict(f) for f in formatos]
    quitar_formato[1]["remove"] = "1"
    html = logged_in.post(f"/examenes/{antes['id']}", data=_datos(
        code="AIB-C01", dominios=dominios, formatos=quitar_formato)).get_data(as_text=True)
    assert "El formato de 5 opciones con 2 correctas lo usan 4 preguntas y no se puede quitar" in html

    cambiar_formato = [dict(f) for f in formatos]
    cambiar_formato[0]["option_count"] = "3"
    html = logged_in.post(f"/examenes/{antes['id']}", data=_datos(
        code="AIB-C01", dominios=dominios, formatos=cambiar_formato)).get_data(as_text=True)
    assert "lo usan 40 preguntas: no se puede cambiar" in html

    assert _examen(app, "AIB-C01") == antes


def test_intercambiar_numeros_de_dominio_y_quitar_uno_vacio(app, logged_in, limpiar):
    logged_in.post("/examenes/nuevo", data=_datos(dominios=[
        {"number": "1", "short_name": "Uno", "name": "Uno", "weight": "50"},
        {"number": "2", "short_name": "Dos", "name": "Dos", "weight": "30"},
        {"number": "3", "short_name": "Tres", "name": "Tres", "weight": "20"},
    ]))
    e = _examen(app, "NUEVO-1")
    (id1, *_a), (id2, *_b), (id3, *_c) = e["domains"]
    dominios = [
        {"id": str(id1), "number": "2", "short_name": "Uno", "name": "Uno", "weight": "50"},
        {"id": str(id2), "number": "1", "short_name": "Dos", "name": "Dos", "weight": "50"},
        {"id": str(id3), "number": "3", "short_name": "Tres", "name": "Tres", "weight": "0", "remove": "1"},
    ]
    formatos = [{"id": str(i), "option_count": str(o), "correct_count": str(c), "target_share_pct": ""}
                for i, o, c, _t in e["formats"]]
    respuesta = logged_in.post(f"/examenes/{e['id']}", data=_datos(dominios=dominios, formatos=formatos))
    assert respuesta.status_code == 302, respuesta.get_data(as_text=True)[:2000]
    despues = _examen(app, "NUEVO-1")
    assert [(i, n, s) for i, n, s, _w, _sk in despues["domains"]] == [(id2, 1, "Dos"), (id1, 2, "Uno")]


def test_archivar_y_borrar(app, logged_in, limpiar):
    aib = _examen(app, "AIB-C01")
    # El único sin archivar no se puede archivar: la aplicación necesita uno en curso.
    logged_in.post(f"/examenes/{aib['id']}/archivar")
    with app.app_context():
        assert db.session.get(Exam, aib["id"]).archived is False

    logged_in.post("/examenes/nuevo", data=_datos())
    nuevo = _examen(app, "NUEVO-1")
    logged_in.post(f"/examenes/{nuevo['id']}/archivar")
    with app.app_context():
        assert db.session.get(Exam, nuevo["id"]).archived is True

    # AIB-C01 tiene preguntas: no se borra.
    html = logged_in.post(f"/examenes/{aib['id']}/borrar", follow_redirects=True).get_data(as_text=True)
    assert "no se puede borrar sin perderlas" in html
    # El nuevo está vacío: se borra con sus dominios, formatos y habilidades.
    logged_in.post(f"/examenes/{nuevo['id']}/borrar")
    with app.app_context():
        assert db.session.get(Exam, nuevo["id"]) is None
        assert Domain.query.filter_by(exam_id=nuevo["id"]).count() == 0
