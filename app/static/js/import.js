(function () {
  "use strict";

  var raw = document.getElementById("raw");
  var previewBox = document.getElementById("preview");
  var previewBtn = document.getElementById("preview-btn");

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
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.error || "Error de red");
        return data;
      });
    });
  }

  function renderPreview(data) {
    var h = "";
    h += "<p><b>" + data.accepted.length + "</b> preguntas listas para insertar";
    if (data.rejected.length) h += ", <b>" + data.rejected.length + "</b> descartadas";
    h += ".</p>";

    if (data.accepted.length) {
      h += "<h2>Entran</h2><ul class=\"import-list\">";
      data.accepted.forEach(function (q) {
        h += "<li><b>" + esc(q.ext_id) + "</b> (dominio " + q.domain + ") — " + esc(q.stem.slice(0, 100)) + (q.stem.length > 100 ? "…" : "") + "</li>";
      });
      h += "</ul>";
    }

    if (data.rejected.length) {
      h += "<h2>Se descartan</h2><ul class=\"import-list\">";
      data.rejected.forEach(function (r) {
        h += "<li>" + esc(r.identifier) + " — <span class=\"reason\">" + esc(r.reason) + "</span></li>";
      });
      h += "</ul>";
    }

    if (data.accepted.length) {
      h += '<div class="acts"><button class="btn" id="confirm-btn">Confirmar e insertar ' + data.accepted.length + " preguntas</button></div>";
    }

    previewBox.innerHTML = h;

    var confirmBtn = document.getElementById("confirm-btn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        confirmBtn.disabled = true;
        post("/preguntas/confirm", { raw: raw.value })
          .then(function (result) {
            previewBox.innerHTML =
              '<p class="tools msg">Insertadas ' + result.inserted + " preguntas.</p>";
            raw.value = "";
            setTimeout(function () { window.location.reload(); }, 1200);
          })
          .catch(function (err) {
            previewBox.innerHTML = '<p class="error">' + esc(err.message) + "</p>";
          });
      });
    }
  }

  previewBtn.addEventListener("click", function () {
    var text = raw.value.trim();
    if (!text) {
      previewBox.innerHTML = '<p class="error">Pega primero el bloque de preguntas.</p>';
      return;
    }
    post("/preguntas/preview", { raw: text }).then(renderPreview).catch(function (err) {
      previewBox.innerHTML = '<p class="error">' + esc(err.message) + "</p>";
    });
  });
})();
