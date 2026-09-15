/* Importación de preguntas: vista previa obligatoria antes de insertar.
 * El marcado está en los <template> de import.html; aquí solo se rellena.
 */
(function () {
  "use strict";

  var raw = document.getElementById("raw");
  var previewBox = document.getElementById("preview");
  var previewBtn = document.getElementById("preview-btn");

  function tpl(id) {
    return document.getElementById(id).content.firstElementChild.cloneNode(true);
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data.error || "El servidor ha respondido con un error.");
        return data;
      });
    }, function () {
      throw new Error("No se ha podido contactar con el servidor. Comprueba la conexión y vuelve a intentarlo.");
    });
  }

  function showMessage(text, cls) {
    var p = document.createElement("p");
    p.className = cls;
    p.textContent = text;
    previewBox.replaceChildren(p);
  }

  function fillList(group, items, describe) {
    if (!items.length) return;
    group.hidden = false;
    var ul = group.querySelector(".import-list");
    items.forEach(function (item) {
      var li = tpl("tpl-import-item");
      var parts = describe(item);
      li.querySelector(".tag").textContent = parts[0];
      li.querySelector(".text").textContent = parts[1];
      if (parts[2]) li.querySelector(".text").classList.add("reason");
      ul.appendChild(li);
    });
  }

  function renderPreview(data) {
    var node = tpl("tpl-preview");

    var summary = data.accepted.length + " preguntas listas para insertar";
    if (data.rejected.length) summary += ", " + data.rejected.length + " descartadas";
    node.querySelector(".summary").textContent = summary + ".";

    fillList(node.querySelector(".accepted"), data.accepted, function (q) {
      var stem = q.stem.length > 110 ? q.stem.slice(0, 110) + "…" : q.stem;
      return [q.ext_id + " · d" + q.domain, stem];
    });

    fillList(node.querySelector(".rejected"), data.rejected, function (r) {
      return [r.identifier, r.reason, true];
    });

    if (data.accepted.length) {
      var acts = node.querySelector(".acts");
      acts.hidden = false;
      var btn = acts.querySelector('[data-act="confirm"]');
      btn.textContent = "Confirmar e insertar " + data.accepted.length + " preguntas";
      btn.addEventListener("click", function () {
        btn.disabled = true;
        post(window.IMPORT_URLS.confirm, { raw: raw.value })
          .then(function (result) {
            showMessage("Insertadas " + result.inserted + " preguntas. Recargando…", "ok-msg");
            raw.value = "";
            setTimeout(function () { window.location.reload(); }, 1200);
          })
          .catch(function (err) { showMessage(err.message, "error"); });
      });
    }

    previewBox.replaceChildren(node);
  }

  previewBtn.addEventListener("click", function () {
    var text = raw.value.trim();
    if (!text) {
      showMessage("Pega primero el bloque de preguntas en el cuadro de arriba.", "error");
      return;
    }
    post(window.IMPORT_URLS.preview, { raw: text })
      .then(renderPreview)
      .catch(function (err) { showMessage(err.message, "error"); });
  });
})();
