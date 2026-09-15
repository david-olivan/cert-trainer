/* Tanda de práctica.
 *
 * El marcado está en las plantillas <template> de session.html: aquí solo
 * se clona y se rellena con textContent. El servidor sigue siendo el único
 * que sabe cuál es la respuesta correcta; este archivo nunca la deduce.
 */
(function () {
  "use strict";

  var LETTERS = "ABCDEFGH".split("");
  var DOMAIN_SHORT = { 1: "Fundamentos", 2: "Estrategia", 3: "Gobernanza", 4: "Transformación" };
  var PASS = window.PASS_THRESHOLD || 72;

  var app = document.getElementById("app");
  var params = new URLSearchParams(window.location.search);
  var mode = params.get("mode");
  var domain = params.get("domain") ? parseInt(params.get("domain"), 10) : null;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Estado local mínimo: lo que hace falta para pintar, nunca para decidir
  // si la respuesta es correcta.
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

  // Nodos de la pregunta en curso, para no volver a buscarlos en cada toque.
  var view = null;

  /* ---- utilidades ---------------------------------------------------- */

  function tpl(id) {
    return document.getElementById(id).content.firstElementChild.cloneNode(true);
  }

  function request(url, options) {
    return fetch(url, options).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.error || "El servidor ha respondido con un error.");
        return data;
      }).catch(function (err) {
        if (err instanceof SyntaxError) {
          throw new Error("El servidor ha devuelto una respuesta que no se entiende. Vuelve a intentarlo.");
        }
        throw err;
      });
    }, function () {
      throw new Error("No se ha podido contactar con el servidor. Comprueba la conexión y vuelve a intentarlo.");
    });
  }

  function post(url, body) {
    return request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  function get(url) {
    return request(url, {});
  }

  function show(node) {
    app.replaceChildren(node);
  }

  function clockStr() {
    var s = Math.max(0, state.secondsLeft);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  /* ---- ciclo de la tanda --------------------------------------------- */

  function start() {
    post(window.APP_URLS.start, { mode: mode, domain: domain })
      .then(function (data) {
        state.total = data.total;
        if (state.timed) {
          state.secondsLeft = data.total * data.minutes_per_question * 60;
          startTicker();
        }
        loadQuestion(data);
      })
      .catch(showError);
  }

  function loadQuestion(data) {
    state.question = data.question;
    state.index = data.index;
    state.total = data.total;
    state.sel = [];
    state.shown = false;
    state.verdict = null;
    state.questionStartedAt = Date.now();
    mountQuestion();
  }

  function startTicker() {
    if (state.tick) clearInterval(state.tick);
    state.tick = setInterval(function () {
      state.secondsLeft--;
      if (view && view.clock) {
        view.clock.textContent = clockStr() + " · ";
        view.clock.classList.toggle("urgent", state.secondsLeft <= 60);
      }
      if (state.secondsLeft <= 0) {
        clearInterval(state.tick);
        finish();
      }
    }, 1000);
  }

  function stopTicker() {
    if (state.tick) clearInterval(state.tick);
    state.tick = null;
  }

  /* ---- pintado -------------------------------------------------------- */

  function mountQuestion() {
    var q = state.question;
    var node = tpl("tpl-question");
    if (!reduceMotion) node.classList.add("q-enter");

    view = {
      root: node,
      dom: node.querySelector(".dom"),
      clock: node.querySelector(".clock"),
      count: node.querySelector(".count"),
      prog: node.querySelector(".prog i"),
      stem: node.querySelector(".stem"),
      instr: node.querySelector(".instr"),
      opts: node.querySelector(".opts"),
      hintline: node.querySelector(".hintline"),
      hintbtn: node.querySelector(".hintbtn"),
      verdictSlot: node.querySelector(".verdict-slot"),
      check: node.querySelector('[data-act="check"]'),
      quit: node.querySelector('[data-act="quit"]'),
    };

    view.dom.textContent = "Dominio " + q.domain + " · " + (q.domain_short || DOMAIN_SHORT[q.domain]);
    view.count.textContent = (state.index + 1) + " de " + state.total;
    if (state.timed) {
      view.clock.hidden = false;
      view.clock.textContent = clockStr() + " · ";
    }
    view.stem.textContent = q.stem;
    view.instr.hidden = q.type !== "m";
    view.check.textContent = state.timed ? "Siguiente" : "Comprobar";

    q.options.forEach(function (text, i) {
      var opt = tpl("tpl-option");
      opt.querySelector(".k").textContent = LETTERS[i];
      opt.querySelector(".txt").textContent = text;
      opt.addEventListener("click", function () { toggle(i); });
      view.opts.appendChild(opt);
    });

    if (q.hint) {
      view.hintline.hidden = false;
      view.hintbtn.addEventListener("click", function () {
        view.hintline.textContent = q.hint;
        view.hintline.classList.add("revealed");
      });
    }

    view.check.addEventListener("click", check);
    view.quit.addEventListener("click", quit);

    show(node);
    // La barra de progreso se anima desde su valor anterior al entrar.
    requestAnimationFrame(function () {
      view.prog.style.width = (state.index / state.total * 100) + "%";
    });
  }

  function paintOptions() {
    var buttons = view.opts.children;
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      b.classList.toggle("sel", !state.shown && state.sel.indexOf(i) >= 0);
      if (state.shown) {
        b.disabled = true;
        b.classList.toggle("ok", state.verdict.correct_options.indexOf(i) >= 0);
        b.classList.toggle("bad", state.verdict.correct_options.indexOf(i) < 0 && state.sel.indexOf(i) >= 0);
      }
    }
    view.check.disabled = !state.shown && state.sel.length === 0;
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
    paintOptions();
  }

  function check() {
    view.check.disabled = true;
    var seconds = Math.round((Date.now() - state.questionStartedAt) / 1000);
    post(window.APP_URLS.answer, { selected: state.sel, seconds_spent: seconds })
      .then(function (data) {
        state.verdict = data;
        // En simulacro no se muestra la explicación: se encadena la siguiente.
        if (state.timed) return advance();
        state.shown = true;
        showVerdict();
      })
      .catch(showError);
  }

  function showVerdict() {
    paintOptions();
    if (view.hintline) view.hintline.hidden = true;

    var node = tpl("tpl-verdict");
    var ok = state.verdict.is_correct;
    node.classList.add(ok ? "ok" : "bad");
    node.querySelector("b").textContent = ok ? "Correcta" : "Incorrecta";
    node.querySelector("p").textContent = state.verdict.explanation;
    node.querySelector(".ref").textContent = "Habilidad " + state.verdict.skill + " de la guía oficial";
    view.verdictSlot.replaceChildren(node);

    view.check.textContent = state.index + 1 >= state.total ? "Ver resultado" : "Siguiente";
    view.check.disabled = false;
    view.check.replaceWith(view.check.cloneNode(true));
    view.check = view.root.querySelector('[data-act="check"]');
    view.check.addEventListener("click", advance);
  }

  function advance() {
    get(window.APP_URLS.next)
      .then(function (data) {
        if (data.done) return finish();
        loadQuestion(data);
      })
      .catch(showError);
  }

  function finish() {
    stopTicker();
    post(window.APP_URLS.finish).then(renderResults).catch(showError);
  }

  function quit() {
    stopTicker();
    // Cierra la tanda en el servidor (lo respondido ya está guardado)
    // antes de volver al inicio.
    post(window.APP_URLS.finish)
      .catch(function () { /* volver al inicio igualmente */ })
      .then(function () { window.location.href = window.APP_URLS.home; });
  }

  /* ---- resultado ------------------------------------------------------ */

  function renderResults(data) {
    stopTicker();
    view = null;

    var node = tpl("tpl-results");
    var pass = data.score_pct >= PASS;

    node.querySelector(".sub").textContent =
      data.correct + " de " + data.answered + " correctas";

    var band = node.querySelector(".band");
    band.classList.add(pass ? "pass" : "fail");
    band.textContent = pass
      ? "Por encima del umbral orientativo del " + PASS + " %."
      : "Por debajo del umbral orientativo del " + PASS + " %.";

    var grid = node.querySelector(".dgrid");
    var bars = [];
    Object.keys(data.per_domain_pct).sort().forEach(function (d) {
      var row = tpl("tpl-domain-row");
      row.querySelector(".name").textContent = "Dominio " + d + " · " + DOMAIN_SHORT[d];
      row.querySelector(".val").textContent = data.per_domain_pct[d] + " %";
      bars.push([row.querySelector(".minibar i"), data.per_domain_pct[d]]);
      grid.appendChild(row);
    });

    var again = node.querySelector('[data-act="again"]');
    again.addEventListener("click", start);

    show(node);

    var score = node.querySelector(".score");
    countUp(score, data.score_pct);
    requestAnimationFrame(function () {
      bars.forEach(function (pair) { pair[0].style.width = pair[1] + "%"; });
    });
  }

  // La puntuación cuenta hacia arriba: el número es el dato principal de la
  // pantalla y el conteo dirige la mirada hacia él.
  function countUp(el, target) {
    if (reduceMotion || target === 0) {
      el.textContent = target + " %";
      return;
    }
    var duration = 700;
    var startedAt = null;
    function frame(now) {
      if (startedAt === null) startedAt = now;
      var t = Math.min(1, (now - startedAt) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(target * eased) + " %";
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* ---- errores -------------------------------------------------------- */

  function showError(err) {
    stopTicker();
    view = null;
    var node = tpl("tpl-error");
    node.querySelector(".error").textContent = err.message;
    show(node);
  }

  if (!mode) {
    showError(new Error("Falta indicar el modo de práctica. Vuelve al inicio y elige uno."));
  } else {
    start();
  }
})();
