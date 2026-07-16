const form = document.getElementById("linkedin-form");
const resumeInput = document.getElementById("li-resume");
const clearResumeBtn = document.getElementById("li-clear-resume");
const fileLabel = document.getElementById("li-file-label");
const postInput = document.getElementById("li-post");
const urlInput = document.getElementById("li-url");
const textField = document.getElementById("li-text-field");
const urlField = document.getElementById("li-url-field");
const analyzeBtn = document.getElementById("li-analyze-btn");
const statusEl = document.getElementById("li-status");
const matchPanel = document.getElementById("li-match");
const jobTitleEl = document.getElementById("li-job-title");
const jobCompanyEl = document.getElementById("li-job-company");
const matchScoreEl = document.getElementById("li-match-score");
const matchReasonsEl = document.getElementById("li-match-reasons");
const matchHintEl = document.getElementById("li-match-hint");
const genLetterBtn = document.getElementById("li-gen-letter");
const genEmailBtn = document.getElementById("li-gen-email");
const genDmBtn = document.getElementById("li-gen-dm");
const outputWrap = document.getElementById("li-output-modal");
const outputTitle = document.getElementById("li-output-title");
const outputClose = document.getElementById("li-output-close");
const genStatus = document.getElementById("li-gen-status");
const editorMount = document.getElementById("li-editor");
const pdfBtn = document.getElementById("li-pdf");

const DEFAULT_FILE_HINT =
  "Obligatoire pour calculer la correspondance et rédiger le texte.";

let savedResumeFile = null;
let lastAnalysis = null;
let resolvedPostText = "";
let lastGenKind = "cover_letter";

const GEN_BUTTONS = [genLetterBtn, genEmailBtn, genDmBtn];

const OUTPUT_TITLES = {
  cover_letter: "Lettre de motivation",
  linkedin_dm: "Message privé LinkedIn",
  email: "E-mail de candidature",
};

const liEditor = window.createDocEditor?.(editorMount, {
  getKind: () => lastGenKind,
  getContext: () => ({
    title: lastAnalysis?.job?.title || "",
    company: lastAnalysis?.job?.company || "",
  }),
  onStatus: (message, isError) => {
    if (genStatus) {
      genStatus.textContent = message;
      genStatus.className = isError ? "status error" : "hint";
    }
  },
});

function setGenerateButtonsDisabled(disabled) {
  GEN_BUTTONS.forEach((btn) => {
    if (btn) btn.disabled = disabled;
  });
}

function getPostMode() {
  return form?.querySelector('input[name="post_mode"]:checked')?.value || "text";
}

function syncPostMode() {
  const mode = getPostMode();
  const isUrl = mode === "url";
  if (textField) textField.hidden = isUrl;
  if (urlField) urlField.hidden = !isUrl;
}

function hideOutputPanel() {
  if (!outputWrap) return;
  outputWrap.hidden = true;
  liEditor?.clear();
  if (genStatus) genStatus.textContent = "";
  if (pdfBtn) pdfBtn.hidden = true;
}

function showOutputPanel() {
  if (!outputWrap) return;
  outputWrap.hidden = false;
}

function syncClearResume() {
  if (clearResumeBtn) {
    clearResumeBtn.hidden = !(resumeInput?.files?.length || savedResumeFile);
  }
}

function clearResume() {
  if (resumeInput) resumeInput.value = "";
  savedResumeFile = null;
  if (fileLabel) fileLabel.textContent = DEFAULT_FILE_HINT;
  syncClearResume();
}

function getPostPayload() {
  const mode = getPostMode();
  if (mode === "url") {
    return { post: "", url: (urlInput?.value || "").trim() };
  }
  return { post: (postInput?.value || "").trim(), url: "" };
}

function appendPostFields(data) {
  const { post, url } = getPostPayload();
  data.append("post", post);
  data.append("url", url);
  return { post, url };
}

resumeInput?.addEventListener("change", () => {
  const file = resumeInput.files?.[0] || null;
  savedResumeFile = file;
  if (fileLabel) {
    fileLabel.textContent = file ? `Fichier : ${file.name}` : DEFAULT_FILE_HINT;
  }
  syncClearResume();
});

clearResumeBtn?.addEventListener("click", clearResume);
form?.querySelectorAll('input[name="post_mode"]').forEach((radio) => {
  radio.addEventListener("change", syncPostMode);
});
syncClearResume();
syncPostMode();
hideOutputPanel();

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideOutputPanel();
  matchPanel.hidden = true;
  lastAnalysis = null;
  resolvedPostText = "";

  const file = resumeInput?.files?.[0] || savedResumeFile;
  const { post, url } = getPostPayload();

  if (!file) {
    showStatus("Importez votre CV avant d’analyser.", true);
    return;
  }
  if (!post && !url) {
    showStatus(
      getPostMode() === "url"
        ? "Saisissez l’URL du post LinkedIn."
        : "Collez le texte du post LinkedIn.",
      true
    );
    return;
  }

  if (getPostMode() === "text" && looksLikeUrlOnly(post)) {
    showStatus(
      "En mode « Texte collé », un lien seul ne suffit pas. Collez le contenu du post LinkedIn, ou basculez sur « URL du post ».",
      true
    );
    return;
  }

  if (resumeInput?.files?.[0]) savedResumeFile = resumeInput.files[0];

  showStatus("Analyse en cours…", false);
  analyzeBtn.disabled = true;

  try {
    const data = new FormData();
    data.append("resume", file);
    appendPostFields(data);
    const response = await fetch("/api/linkedin/analyze", { method: "POST", body: data });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "Analyse impossible");

    lastAnalysis = payload;
    resolvedPostText = payload.resolved_text || post || "";
    statusEl.hidden = true;

    const job = payload.job || {};
    jobTitleEl.textContent = job.title || "Offre LinkedIn";
    jobCompanyEl.textContent =
      job.company && job.company !== "entreprise" ? job.company : "LinkedIn";
    matchScoreEl.textContent = `${payload.match_percent ?? "—"} % de correspondance`;
    const reasons = (payload.match_reasons || []).join("; ");
    matchReasonsEl.innerHTML = reasons
      ? `<strong>Pourquoi :</strong> ${escapeHtml(reasons)}`
      : "";
    matchHintEl.textContent = payload.hint || "";
    matchPanel.hidden = false;
  } catch (err) {
    showStatus(err.message || "Erreur", true);
  } finally {
    analyzeBtn.disabled = false;
  }
});

async function generate(kind) {
  const file = resumeInput?.files?.[0] || savedResumeFile;
  const { post, url } = getPostPayload();

  if (!file) {
    showStatus("Importez votre CV avant de générer.", true);
    return;
  }
  if (!post && !url && !resolvedPostText) {
    showStatus("Ajoutez d’abord un post (texte ou URL).", true);
    return;
  }

  setGenerateButtonsDisabled(true);
  showStatus("Génération en cours…", false);
  lastGenKind = kind;

  try {
    const data = new FormData();
    data.append("resume", file);
    data.append("kind", kind);
    // Reuse resolved text from analysis when URL mode already succeeded
    if (resolvedPostText && getPostMode() === "url") {
      data.append("post", resolvedPostText);
      data.append("url", "");
    } else {
      appendPostFields(data);
    }
    const response = await fetch("/api/linkedin/generate", { method: "POST", body: data });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "La génération a échoué");

    statusEl.hidden = true;
    showOutputPanel();
    outputTitle.textContent = OUTPUT_TITLES[kind] || "Texte généré";
    liEditor?.setHtml(
      payload.content_html || window.docPlainToHtml?.(payload.content || "") || payload.content || ""
    );
    if (pdfBtn) {
      pdfBtn.hidden = kind !== "cover_letter";
      pdfBtn.disabled = false;
    }
    genStatus.textContent =
      payload.engine === "llm"
        ? "Texte prêt — vous pouvez le modifier et l’améliorer ci-dessous."
        : "Texte local — modifiez-le ou ajoutez OPENAI_API_KEY pour l’IA.";
  } catch (err) {
    hideOutputPanel();
    showStatus(err.message || "Erreur de génération", true);
  } finally {
    setGenerateButtonsDisabled(false);
  }
}

const pdfContactError = document.getElementById("pdf-contact-error");
const pdfContactErrorList = document.getElementById("pdf-contact-error-list");
const pdfContactErrorClose = document.getElementById("pdf-contact-error-close");
const pdfContactErrorOk = document.getElementById("pdf-contact-error-ok");

const CONTACT_GAPS = {
  address: "⚠️ Veuillez renseigner votre adresse complète.",
  phone: "⚠️ Veuillez renseigner votre numéro de téléphone.",
  email: "⚠️ Veuillez renseigner votre adresse e-mail.",
};

// Field present but not well-formed — mirrors job_agent.validators (Python is the
// authoritative gate; this is only a same-wording client-side pre-check).
const CONTACT_INVALID = {
  address: "⚠️ Veuillez renseigner une adresse complète valide.",
  phone: "⚠️ Veuillez renseigner un numéro de téléphone valide.",
  email: "⚠️ Veuillez renseigner une adresse e-mail valide.",
};

const ADDRESS_KEYWORDS = [
  "street", "st", "road", "rd", "avenue", "ave", "boulevard", "blvd",
  "route", "rue", "bd", "lot", "lotissement", "résidence", "residence",
  "immeuble", "imm", "bloc", "building", "apartment", "appartement",
  "hay", "quartier", "city",
];
const ADDRESS_KEYWORD_RE = new RegExp(
  "\\b(" + ADDRESS_KEYWORDS.join("|") + ")\\b",
  "i"
);
const MIN_ADDRESS_LENGTH = 8;
const ADDRESS_SCORE_THRESHOLD = 2;

function isValidEmail(value) {
  const candidate = String(value || "").trim();
  if (!candidate) return false;
  return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(candidate);
}

function normalizePhone(value) {
  return String(value || "").trim().replace(/[\s\-()]+/g, "");
}

function isValidPhone(value) {
  const normalized = normalizePhone(value);
  if (!normalized) return false;
  return /^\+?\d{9,15}$/.test(normalized);
}

function addressValidationScore(value) {
  const candidate = String(value || "").trim();
  if (!candidate) return 0;
  let score = 0;
  if (candidate.length >= MIN_ADDRESS_LENGTH) score += 1;
  if (/\d/.test(candidate)) score += 1;
  if (ADDRESS_KEYWORD_RE.test(candidate)) score += 1;
  return score;
}

function isValidAddress(value) {
  return addressValidationScore(value) >= ADDRESS_SCORE_THRESHOLD;
}

function isCoverLetterHeaderTerminator(ln) {
  const low = String(ln || "").toLowerCase().trim();
  if (!low) return false;
  if (low.startsWith("objet")) return true;
  if (/^(?:le\s+)?\d{1,2}\s+\S+\s+\d{4}\b/i.test(ln.trim())) return true;
  if (/,\s*le\s+\d{1,2}\s+/i.test(ln)) return true;
  if (
    ln.trim().endsWith(",") &&
    ["madame", "monsieur", "bonjour", "chère", "cher"].some((w) => low.includes(w))
  ) {
    return true;
  }
  if (ln.trim().length > 100) return true;
  if (/^(je |j’|j'|nous |motiv|disponib)/i.test(low)) return true;
  return false;
}

function parseCoverLetterContacts(text) {
  const lines = String(text || "").split("\n").map((l) => l.trim());
  let i = 0;
  while (i < lines.length && !lines[i]) i += 1;
  if (i >= lines.length) return { address: "", phone: "", email: "" };
  i += 1;
  const collected = [];
  while (i < lines.length && collected.length < 3) {
    const ln = lines[i];
    i += 1;
    if (!ln) continue;
    if (isCoverLetterHeaderTerminator(ln)) break;
    if (ln.startsWith("⚠️") || ln.toLowerCase().includes("veuillez renseigner")) continue;
    collected.push(ln);
  }
  let address = "";
  let phone = "";
  let email = "";
  for (const item of collected) {
    if (item.includes("@") && !email) email = item;
    else if (/\d/.test(item) && !phone && !item.includes("@")) phone = item;
    else if (!address) address = item;
  }
  if (collected.length === 3) {
    [address, phone, email] = collected;
  }
  return { address, phone, email };
}

/** Warnings for fields missing from the letter OR failing format validation. */
function coverLetterMissingContacts(text) {
  const { address, phone, email } = parseCoverLetterContacts(text);
  const missing = [];
  if (!address) missing.push(CONTACT_GAPS.address);
  else if (!isValidAddress(address)) missing.push(CONTACT_INVALID.address);
  if (!phone) missing.push(CONTACT_GAPS.phone);
  else if (!isValidPhone(phone)) missing.push(CONTACT_INVALID.phone);
  if (!email) missing.push(CONTACT_GAPS.email);
  else if (!isValidEmail(email)) missing.push(CONTACT_INVALID.email);
  return missing;
}

function showPdfContactError(messages) {
  if (!pdfContactError || !pdfContactErrorList) return;
  pdfContactErrorList.innerHTML = messages
    .map((m) => `<li>${String(m).replaceAll("<", "&lt;")}</li>`)
    .join("");
  pdfContactError.hidden = false;
}

function hidePdfContactError() {
  if (pdfContactError) pdfContactError.hidden = true;
}

pdfContactErrorClose?.addEventListener("click", hidePdfContactError);
pdfContactErrorOk?.addEventListener("click", hidePdfContactError);

genLetterBtn?.addEventListener("click", () => generate("cover_letter"));
genEmailBtn?.addEventListener("click", () => generate("email"));
genDmBtn?.addEventListener("click", () => generate("linkedin_dm"));

// Stay open until × is clicked (no outside-click close)
outputClose?.addEventListener("click", () => {
  hidePdfContactError();
  hideOutputPanel();
});

pdfBtn?.addEventListener("click", async () => {
  const content = (liEditor?.getText() || "").trim();
  if (!content) {
    showStatus("Aucun texte à exporter.", true);
    return;
  }
  const missing = coverLetterMissingContacts(content);
  if (missing.length) {
    showPdfContactError(missing);
    return;
  }
  pdfBtn.disabled = true;
  const prev = pdfBtn.textContent;
  pdfBtn.textContent = "Export…";
  try {
    const response = await fetch("/api/export/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: liEditor?.getHtml() || content,
        title: lastAnalysis?.job?.title || "",
        kind: "cover_letter",
      }),
    });
    if (!response.ok) {
      const errPayload = await response.json().catch(() => ({}));
      const errText = errPayload.error || "Export PDF impossible";
      if (String(errText).includes("Veuillez renseigner") || String(errText).includes("⚠️")) {
        showPdfContactError(
          String(errText)
            .split("\n")
            .map((l) => l.trim())
            .filter(Boolean)
        );
      } else {
        throw new Error(errText);
      }
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = /filename="([^"]+)"/.exec(disposition);
    a.href = url;
    a.download = match?.[1] || "lettre_motivation.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (genStatus) genStatus.textContent = "PDF téléchargé.";
  } catch (err) {
    showStatus(err.message || "Export PDF impossible", true);
  } finally {
    pdfBtn.disabled = false;
    pdfBtn.textContent = prev;
  }
});

function looksLikeUrlOnly(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  const residual = text
    .replace(/https?:\/\/\S+/gi, " ")
    .replace(/\bwww\.\S+/gi, " ")
    .replace(/\blnkd\.in\/\S+/gi, " ")
    .replace(/\S*linkedin\.com\S*/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (residual.length <= 12) return true;
  const lines = text.split(/\n/).map((l) => l.trim()).filter(Boolean);
  if (
    lines.length === 1 &&
    /https?:\/\/|linkedin\.com|lnkd\.in/i.test(lines[0]) &&
    residual.length < 40
  ) {
    return true;
  }
  return false;
}

function showStatus(message, isError) {
  statusEl.hidden = false;
  statusEl.className = isError ? "status error" : "status";
  statusEl.textContent = message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
