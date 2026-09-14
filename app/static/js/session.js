(function () {
  "use strict";

  var LETTERS = "ABCDE".split("");
  var app = document.getElementById("app");
  var params = new URLSearchParams(window.location.search);
  var mode = params.get("mode");
  var domain = params.get("domain") ? parseInt(params.get("domain"), 10) : null;

  // Estado local mínimo: lo que se necesita para pintar, no para decidir si
  // la respuesta es correcta (eso lo decide siempre el servidor).
  var state = {
    question: null,
    index: 0,
    total: 0,
    sel: [],
    shown: false,
    verdict: null,
    timed: mode === "simulacro",
    secondsLeft: 0,
    questionStartedAt: null,
    tick: null,
  };

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || "Error de red"); });
      return r.json();
    });
  }

  function get(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || "Error de red"); });
      return r.json();
    });
  }

  function clockStr() {
    var s = Math.max(0, state.secondsLeft);
    var m = Math.floor(s / 60);
    return m + ":" + String(s % 60).padStart(2, "0");
  }

  function start() {
    post(window.APP_URLS.start, { mode: mode, domain: domain })
      .then(function (data) {
        state.question = data.question;
        state.index = data.index;
        state.total = data.total;
        state.sel = [];
        state.shown = false;
        state.verdict = null;
        state.questionStartedAt = Date.now();
        if (state.timed) {
          state.secondsLeft = data.total * data.minutes_per_question * 60;
          startTicker();
        }
        render();
      })
      .catch(showError);
  }

  function startTicker() {
    if (state.tick) clearInterval(state.tick);
    state.tick = setInterval(function () {
      state.secondsLeft--;
      var el = document.getElementById("clock");
      if (el) el.textContent = clockStr();
      if (state.secondsLeft <= 0) {
        clearInterval(state.tick);
        finish();
      }
    }, 1000);
  }

  function toggle(i) {
    if (state.shown) return;
    if (state.question.type === "m") {
      var p = state.sel.indexOf(i);
      if (p < 0) state.sel.push(i);
      else state.sel.splice(p, 1);
    } else {
      state.sel = [i];
    }
    render();
  }

  function secondsOnQuestion() {
    return Math.round((Date.now() - state.questionStartedAt) / 1000);
  }

  function check() {
    var seconds = secondsOnQuestion();
    post(window.APP_URLS.answer, { selected: state.sel, seconds_spent: seconds })
      .then(function (data) {
        state.verdict = data;
        if (state.timed) {
          advance();
        } else {
          state.shown = true;
          render();
        }
      })
      .catch(showError);
  }

  function advance() {
    get(window.APP_URLS.next)
      .then(function (data) {
        if (data.done) {
          finish();
          return;
        }
        state.question = data.question;
        state.index = data.index;
        state.total = data.total;
        state.sel = [];
        state.shown = false;
        state.verdict = null;
        state.questionStartedAt = Date.now();
        render();
      })
      .catch(showError);
  }

  function finish() {
    if (state.tick) clearInterval(state.tick);
    post(window.APP_URLS.finish)
      .then(function (data) {
        renderResults(data);
      })
      .catch(showError);
  }

  function quit() {
    if (state.tick) clearInterval(state.tick);
    // Termina la sesión en el servidor (guarda lo respondido hasta ahora)
    // antes de volver al inicio.
    post(window.APP_URLS.finish).finally(function () {
      window.location.href = window.APP_URLS.home;
    });
  }

  function showError(err) {
    app.innerHTML =
      '<p class="error">' + esc(err.message) + "</p>" +
      '<div class="acts"><a class="btn ghost" href="' + window.APP_URLS.home + '">Volver al inicio</a></div>';
  }

  var DOMAIN_SHORT = { 1: "Fundamentos", 2: "Estrategia", 3: "Gobernanza", 4: "Transformación" };

  function render() {
    var q = state.question;
    var h =
      '<div class="bar"><span class="dom">Dominio ' + q.domain + " · " + esc(q.domain_short || DOMAIN_SHORT[q.domain]) + "</span>" +
      "<span>" +
      (state.timed ? '<span id="clock">' + clockStr() + "</span> · " : "") +
      (state.index + 1) + " de " + state.total +
      "</span></div>" +
      '<div class="prog"><i style="width:' + (state.index / state.total * 100) + '%"></i></div>';

    h += '<p class="stem">' + esc(q.stem) + "</p>";
    if (q.type === "m") {
      h += '<p class="instr">Respuesta múltiple: acierta todas las opciones o la pregunta no puntúa.</p>';
    }

    h += '<div class="opts">';
    q.options.forEach(function (opt, i) {
      var cls = "opt";
      if (state.shown) {
        if (state.verdict.correct_options.indexOf(i) >= 0) cls += " ok";
        else if (state.sel.indexOf(i) >= 0) cls += " bad";
      } else if (state.sel.indexOf(i) >= 0) {
        cls += " sel";
      }
      h +=
        '<button class="' + cls + '" data-i="' + i + '"' + (state.shown ? " disabled" : "") + ">" +
        '<span class="k">' + LETTERS[i] + "</span><span>" + esc(opt) + "</span></button>";
    });
    h += "</div>";

    if (!state.shown && q.hint) {
      h += '<p class="hintline"><button class="hintbtn" id="hint">Ver pista</button></p>';
    }
    if (state.shown) {
      var ok = state.verdict.is_correct;
      h +=
        '<div class="verdict ' + (ok ? "ok" : "bad") + '"><b>' + (ok ? "Correcta" : "Incorrecta") + "</b><p>" +
        esc(state.verdict.explanation) + "</p>" +
        '<span class="ref">Habilidad ' + esc(state.verdict.skill) + " de la guía oficial</span></div>";
    }

    h += '<div class="acts">';
    if (!state.shown) {
      h += '<button class="btn" id="check"' + (state.sel.length ? "" : " disabled") + ">" + (state.timed ? "Siguiente" : "Comprobar") + "</button>";
    } else {
      h += '<button class="btn" id="next">' + (state.index + 1 >= state.total ? "Ver resultado" : "Siguiente") + "</button>";
    }
    h += '<button class="btn ghost" id="quit">Salir</button></div>';

    app.innerHTML = h;
    bind();
  }

  function renderResults(data) {
    if (state.tick) clearInterval(state.tick);
    var pass = data.score_pct >= 72;
    var h =
      '<div class="bar"><span class="dom">Resultado</span><span>' + data.correct + " de " + data.answered + "</span></div>" +
      '<div class="score">' + data.score_pct + " %</div>" +
      '<p class="band ' + (pass ? "pass" : "fail") + '">' +
      (pass ? "Por encima del umbral orientativo de aprobado." : "Por debajo del umbral orientativo del 72 %.") +
      "</p>";

    h += '<table class="dtable">';
    Object.keys(data.per_domain_pct).forEach(function (d) {
      var pct = data.per_domain_pct[d];
      h +=
        "<tr><td>Dominio " + d + " · " + esc(DOMAIN_SHORT[d]) + "</td>" +
        '<td style="width:40%"><span class="minibar"><i style="width:' + pct + '%"></i></span></td>' +
        "<td>" + pct + " %</td></tr>";
    });
    h += "</table>";

    h += '<div class="acts"><button class="btn" id="again">Otra tanda</button>' +
      '<a class="btn ghost" href="' + window.APP_URLS.home + '">Volver al inicio</a></div>';

    app.innerHTML = h;
    var again = document.getElementById("again");
    if (again) again.addEventListener("click", start);
  }

  function bind() {
    app.querySelectorAll(".opt").forEach(function (b) {
      b.addEventListener("click", function () {
        toggle(parseInt(b.getAttribute("data-i"), 10));
      });
    });
    var c = document.getElementById("check");
    if (c) c.addEventListener("click", check);
    var n = document.getElementById("next");
    if (n) n.addEventListener("click", advance);
    var qb = document.getElementById("quit");
    if (qb) qb.addEventListener("click", quit);
    var hint = document.getElementById("hint");
    if (hint) {
      hint.addEventListener("click", function () {
        hint.parentNode.textContent = state.question.hint;
        hint.parentNode.style.fontStyle = "italic";
      });
    }
  }

  if (!mode) {
    showError(new Error("Falta el modo de práctica."));
  } else {
    start();
  }
})();
