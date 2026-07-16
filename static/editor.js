/**
 * Shared rich-text document editor (letter / email / LinkedIn DM).
 */
(function (global) {
  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function plainToHtml(text) {
    const blocks = String(text || "")
      .trim()
      .split(/\n\s*\n/);
    return blocks
      .map((block) => {
        const lines = block.split("\n").map((l) => escapeHtml(l));
        return `<p>${lines.join("<br>")}</p>`;
      })
      .join("");
  }

  function createDocEditor(mountEl, options = {}) {
    if (!mountEl) return null;

    mountEl.innerHTML = `
      <div class="doc-editor">
        <div class="doc-toolbar" role="toolbar" aria-label="Mise en forme">
          <button type="button" data-cmd="bold" title="Gras"><b>B</b></button>
          <button type="button" data-cmd="italic" title="Italique"><i>I</i></button>
          <button type="button" data-cmd="underline" title="Souligné"><u>U</u></button>
          <span class="doc-sep"></span>
          <label class="doc-tool-label">Police
            <select data-font>
              <option value="Arial">Arial</option>
              <option value="Calibri">Calibri</option>
              <option value="Times New Roman">Times New Roman</option>
              <option value="Georgia">Georgia</option>
              <option value="DM Sans">DM Sans</option>
            </select>
          </label>
          <label class="doc-tool-label">Taille
            <select data-size>
              <option value="2">Petit</option>
              <option value="3" selected>Normal</option>
              <option value="4">Moyen</option>
              <option value="5">Grand</option>
            </select>
          </label>
          <label class="doc-tool-label">Couleur
            <input type="color" data-color value="#1c2420" />
          </label>
          <span class="doc-sep"></span>
          <button type="button" data-cmd="justifyLeft" title="Aligner à gauche">⟸</button>
          <button type="button" data-cmd="justifyCenter" title="Centrer">≡</button>
          <button type="button" data-cmd="justifyRight" title="Aligner à droite">⟹</button>
          <span class="doc-sep"></span>
          <button type="button" data-cmd="insertUnorderedList" title="Liste à puces">• Liste</button>
          <button type="button" data-cmd="insertOrderedList" title="Liste numérotée">1. Liste</button>
          <button type="button" data-cmd="formatBlock" data-value="blockquote" title="Citation">« »</button>
          <button type="button" data-cmd="indent" title="Indenter">⇥</button>
          <button type="button" data-cmd="outdent" title="Désindenter">⇤</button>
          <span class="doc-sep"></span>
          <button type="button" data-cmd="undo" title="Annuler">↶</button>
          <button type="button" data-cmd="redo" title="Rétablir">↷</button>
          <button type="button" data-cmd="selectAll" title="Tout sélectionner">Tout</button>
          <button type="button" data-cmd="removeFormat" title="Effacer la mise en forme">Effacer style</button>
        </div>
        <div class="doc-surface" contenteditable="true" spellcheck="true" role="textbox" aria-multiline="true"></div>
      </div>
    `;

    const surface = mountEl.querySelector(".doc-surface");

    function exec(cmd, value = null) {
      surface.focus();
      if (cmd === "formatBlock" && value) {
        document.execCommand("formatBlock", false, value);
        return;
      }
      document.execCommand(cmd, false, value);
    }

    mountEl.querySelector(".doc-toolbar")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-cmd]");
      if (!btn) return;
      exec(btn.dataset.cmd, btn.dataset.value || null);
    });

    mountEl.querySelector("[data-font]")?.addEventListener("change", (event) => {
      exec("fontName", event.target.value);
    });
    mountEl.querySelector("[data-size]")?.addEventListener("change", (event) => {
      exec("fontSize", event.target.value);
    });
    mountEl.querySelector("[data-color]")?.addEventListener("input", (event) => {
      exec("foreColor", event.target.value);
    });

    surface.addEventListener("paste", (event) => {
      const plain = event.clipboardData?.getData("text/plain");
      if (!plain) return;
      event.preventDefault();
      document.execCommand("insertHTML", false, plainToHtml(plain));
    });

    function setHtml(html) {
      surface.innerHTML = html || "";
    }

    function setPlain(text) {
      setHtml(plainToHtml(text || ""));
    }

    function getHtml() {
      return surface.innerHTML || "";
    }

    function getText() {
      return (surface.innerText || "").trim();
    }

    function clear() {
      surface.innerHTML = "";
    }

    return { setHtml, setPlain, getHtml, getText, clear, el: mountEl };
  }

  global.createDocEditor = createDocEditor;
  global.docPlainToHtml = plainToHtml;
})(window);
