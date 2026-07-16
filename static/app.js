const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const resultsToolbar = document.getElementById("results-toolbar");
const filterCountEl = document.getElementById("filter-count");
const filterToggle = document.getElementById("filter-toggle");
const filterPanel = document.getElementById("filter-panel");
const matchSelect = document.getElementById("match-select");
const dateSelect = document.getElementById("date-select");
const newSelect = document.getElementById("new-select");
const zoneSelect = document.getElementById("zone-select");
const zoneFilterRow = document.getElementById("zone-filter-row");
const regionSelect = document.getElementById("region");
const submitBtn = document.getElementById("submit-btn");
const fileLabel = document.getElementById("file-label");
const resumeInput = document.getElementById("resume");
const queryInput = document.getElementById("query");
const clearQueryBtn = document.getElementById("clear-query");
const clearResumeBtn = document.getElementById("clear-resume");

const modal = document.getElementById("write-modal");
const modalTitle = document.getElementById("modal-title");
const modalJob = document.getElementById("modal-job");
const modalGenerate = document.getElementById("modal-generate");
const modalStatus = document.getElementById("modal-status");
const modalCvMissing = document.getElementById("modal-cv-missing");
const modalImportCv = document.getElementById("modal-import-cv");
const modalEditorMount = document.getElementById("modal-editor");
const modalActions = document.getElementById("modal-actions");
const modalPdf = document.getElementById("modal-pdf");
const modalClose = document.getElementById("modal-close");

const DEFAULT_FILE_HINT =
  "Importez votre CV pour cibler le bon métier et éviter les offres hors profil.";

const EMPTY_SEARCH_MSG =
  "Ajoutez un mot-clé ou importez votre CV (ou les deux) pour simplifier la recherche.";

let savedResumeFile = null;
let searchUsedResume = false;
let pendingKind = null; // cover_letter | email
let pendingJob = null;
const jobsById = {};
let allResults = [];
let minMatchFilter = 0;
let dateSort = "newest";
let zoneFilter = "all";
let newOnlyFilter = false;
let lastSearchRegion = "morocco";

const modalEditor = window.createDocEditor?.(modalEditorMount, {
  getKind: () => pendingKind || "cover_letter",
  getContext: () => ({
    title: pendingJob?.title || "",
    company: pendingJob?.company || "",
  }),
  onStatus: (message, isError) => {
    modalStatus.hidden = false;
    modalStatus.textContent = message;
    modalStatus.className = isError ? "status error" : "hint";
  },
});

function syncClearButtons() {
  if (clearQueryBtn) {
    clearQueryBtn.hidden = !(queryInput?.value || "").trim();
  }
  if (clearResumeBtn) {
    clearResumeBtn.hidden = !(resumeInput?.files?.length || savedResumeFile);
  }
}

function clearQuery() {
  if (!queryInput) return;
  queryInput.value = "";
  syncClearButtons();
  queryInput.focus();
}

function clearResume() {
  if (resumeInput) resumeInput.value = "";
  savedResumeFile = null;
  searchUsedResume = false;
  if (fileLabel) fileLabel.textContent = DEFAULT_FILE_HINT;
  syncClearButtons();
}

function hasSearchInput() {
  const hasQuery = !!(queryInput?.value || "").trim();
  const hasFile = !!(resumeInput?.files?.length || savedResumeFile);
  return hasQuery || hasFile;
}

queryInput?.addEventListener("input", syncClearButtons);
clearQueryBtn?.addEventListener("click", clearQuery);
clearResumeBtn?.addEventListener("click", clearResume);
syncClearButtons();

function showCvMissingBanner() {
  if (modalCvMissing) modalCvMissing.hidden = false;
  if (modalStatus) modalStatus.hidden = true;
}

function hideCvMissingBanner() {
  if (modalCvMissing) modalCvMissing.hidden = true;
}

resumeInput.addEventListener("change", () => {
  const file = resumeInput.files?.[0] || null;
  savedResumeFile = file;
  fileLabel.textContent = file
    ? `Fichier : ${file.name}`
    : DEFAULT_FILE_HINT;
  syncClearButtons();
  // If user imported via modal « Importer maintenant », regenerate
  if (file && pendingKind && pendingJob && modal && !modal.hidden) {
    hideCvMissingBanner();
    queueMicrotask(() => modalGenerate?.click());
  }
});

modalClose.addEventListener("click", closeModal);
// Modal stays open until the user clicks × (no outside-click / backdrop close)

modalImportCv?.addEventListener("click", () => {
  resumeInput?.click();
});

modalGenerate.addEventListener("click", async () => {
  if (!pendingKind || !pendingJob) return;
  const file = resumeInput?.files?.[0] || savedResumeFile;
  if (!file) {
    showCvMissingBanner();
    return;
  }

  hideCvMissingBanner();
  modalGenerate.disabled = true;
  modalStatus.hidden = false;
  modalStatus.className = "hint";
  modalStatus.textContent = "Génération en cours…";
  if (modalEditorMount) modalEditorMount.hidden = true;
  if (modalActions) modalActions.hidden = true;
  modalEditor?.clear();

  try {
    const data = new FormData();
    data.append("resume", file);
    data.append("job_title", pendingJob.title || "");
    data.append("job_company", pendingJob.company || "");
    data.append("job_city", pendingJob.city || pendingJob.location || "");
    data.append("job_location", pendingJob.location || pendingJob.city || "");
    data.append("job_description", pendingJob.description || "");
    data.append("job_url", pendingJob.url || pendingJob.application_url || "");
    data.append("job_source", pendingJob.source || "");

    const endpoint =
      pendingKind === "cover_letter" ? "/api/generate/cover-letter" : "/api/generate/email";
    const response = await fetch(endpoint, { method: "POST", body: data });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "La génération a échoué");

    if (modalEditorMount) modalEditorMount.hidden = false;
    modalEditor?.setHtml(
      payload.content_html || window.docPlainToHtml?.(payload.content || "") || payload.content || ""
    );
    if (modalActions) modalActions.hidden = false;
    if (modalGenerate) {
      modalGenerate.hidden = false;
      modalGenerate.textContent = "Régénérer";
    }
    modalStatus.textContent =
      payload.engine === "llm"
        ? "Texte généré et personnalisé avec votre CV. Vous pouvez le modifier ci-dessous."
        : "Texte généré à partir du CV (mode local). Modifiez-le ou ajoutez OPENAI_API_KEY pour l’IA.";
  } catch (err) {
    modalStatus.textContent = err.message || "Erreur de génération";
    if (modalGenerate) {
      modalGenerate.hidden = false;
      modalGenerate.textContent = "Générer";
    }
  } finally {
    modalGenerate.disabled = false;
  }
});

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
  i += 1; // skip name
  const collected = [];
  while (i < lines.length && collected.length < 3) {
    const ln = lines[i];
    i += 1;
    if (!ln) continue; // blank lines between editor paragraphs
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

/** Warnings for fields missing from the letter OR failing format validation
 * (never the full trio by default — only what actually needs fixing). */
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

modalPdf?.addEventListener("click", async () => {
  const content = (modalEditor?.getText() || "").trim();
  if (!content) {
    modalStatus.hidden = false;
    modalStatus.textContent = "Aucun texte à exporter. Générez d’abord la lettre.";
    return;
  }
  if ((pendingKind || "cover_letter") === "cover_letter") {
    const missing = coverLetterMissingContacts(content);
    if (missing.length) {
      showPdfContactError(missing);
      return;
    }
  }
  modalPdf.disabled = true;
  const prevLabel = modalPdf.textContent;
  modalPdf.textContent = "Export…";
  try {
    const response = await fetch("/api/export/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: modalEditor?.getHtml() || content,
        title: pendingJob?.title || "",
        kind: pendingKind || "cover_letter",
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
    modalStatus.hidden = false;
    modalStatus.textContent = "PDF téléchargé.";
  } catch (err) {
    modalStatus.hidden = false;
    modalStatus.textContent = err.message || "Export PDF impossible";
  } finally {
    modalPdf.disabled = false;
    modalPdf.textContent = prevLabel;
  }
});

document.getElementById("match-filters")?.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-min-match]");
  if (!btn) return;
  minMatchFilter = Number(btn.dataset.minMatch || 0);
  document.querySelectorAll("#match-filters .filter-chip").forEach((el) => {
    el.classList.toggle("is-active", el === btn);
  });
  renderFilteredResults();
});

document.getElementById("date-filters")?.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-date-sort]");
  if (!btn) return;
  dateSort = btn.dataset.dateSort || "newest";
  document.querySelectorAll("#date-filters .filter-chip").forEach((el) => {
    el.classList.toggle("is-active", el === btn);
  });
  renderFilteredResults();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resultsEl.innerHTML = "";
  if (resultsToolbar) resultsToolbar.hidden = true;
  closeFilterPanel();
  allResults = [];

  if (!hasSearchInput()) {
    statusEl.hidden = false;
    statusEl.className = "status error";
    statusEl.textContent = EMPTY_SEARCH_MSG;
    return;
  }

  statusEl.hidden = false;
  statusEl.className = "status";
  statusEl.textContent = "Recherche en cours…";
  submitBtn.disabled = true;

  const fileSent = resumeInput.files?.[0] || null;
  if (fileSent) {
    savedResumeFile = fileSent;
  }
  // Only reuse CV for generation when THIS search actually included a resume upload
  searchUsedResume = !!fileSent;

  const maxAge = form.querySelector('input[name="max_age"]:checked')?.value || "7";

  try {
    const data = new FormData(form);
    const response = await fetch("/api/search", { method: "POST", body: data });
    const payload = await response.json();

    if (!payload.ok) {
      throw new Error(payload.error || "La recherche a échoué");
    }

    statusEl.hidden = true;
    statusEl.textContent = "";

    allResults = payload.results || [];
    lastSearchRegion = payload.region || regionSelect?.value || "morocco";
    minMatchFilter = 0;
    dateSort = "newest";
    zoneFilter = "all";
    newOnlyFilter = false;
    if (matchSelect) matchSelect.value = "0";
    if (dateSelect) dateSelect.value = "newest";
    if (zoneSelect) zoneSelect.value = "all";
    if (newSelect) newSelect.value = "all";
    syncZoneFilterVisibility();

    if (!allResults.length) {
      if (resultsToolbar) resultsToolbar.hidden = true;
      const days = payload.max_age_days || maxAge;
      resultsEl.innerHTML = `<article class="card"><p>Aucune offre assez proche (moins de ${escapeHtml(String(days))} jour(s) et correspondance ≥ 35 %). Modifiez les mots-clés, le CV ou la période.</p></article>`;
      return;
    }

    if (resultsToolbar) resultsToolbar.hidden = false;
    renderFilteredResults();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = "status error";
    statusEl.textContent = err.message || "Erreur";
  } finally {
    submitBtn.disabled = false;
  }
});

function closeFilterPanel() {
  if (!filterPanel || !filterToggle) return;
  filterPanel.hidden = true;
  filterToggle.setAttribute("aria-expanded", "false");
}

function syncZoneFilterVisibility() {
  if (!zoneFilterRow) return;
  zoneFilterRow.hidden = lastSearchRegion !== "all";
  if (lastSearchRegion !== "all") zoneFilter = "all";
}

filterToggle?.addEventListener("click", (event) => {
  event.stopPropagation();
  if (!filterPanel) return;
  const open = filterPanel.hidden;
  filterPanel.hidden = !open;
  filterToggle.setAttribute("aria-expanded", open ? "true" : "false");
});

document.addEventListener("click", (event) => {
  if (!filterPanel || filterPanel.hidden) return;
  const wrap = event.target.closest(".filter-toggle-wrap");
  if (!wrap) closeFilterPanel();
});

matchSelect?.addEventListener("change", () => {
  minMatchFilter = Number(matchSelect.value || 0);
  renderFilteredResults();
});

dateSelect?.addEventListener("change", () => {
  dateSort = dateSelect.value || "newest";
  renderFilteredResults();
});

zoneSelect?.addEventListener("change", () => {
  zoneFilter = zoneSelect.value || "all";
  renderFilteredResults();
});

newSelect?.addEventListener("change", () => {
  newOnlyFilter = (newSelect.value || "all") === "new";
  renderFilteredResults();
});

function getFilteredJobs() {
  let jobs = allResults.filter((job) => {
    const pct = Number(job.match_percent ?? job.score ?? 0);
    if (pct < minMatchFilter) return false;
    if (newOnlyFilter && !job.is_new) return false;
    if (zoneFilter !== "all") {
      const zone = job.tier_label || job.tier || "";
      if (zone !== zoneFilter) return false;
    }
    return true;
  });

  jobs = [...jobs].sort((a, b) => {
    const newA = a.is_new ? 0 : 1;
    const newB = b.is_new ? 0 : 1;
    if (newA !== newB) return newA - newB;
    const ta = Number(a.sort_ts || 0);
    const tb = Number(b.sort_ts || 0);
    if (dateSort === "oldest") return ta - tb;
    return tb - ta;
  });
  return jobs;
}

function renderFilteredResults() {
  const jobs = getFilteredJobs();
  Object.keys(jobsById).forEach((k) => delete jobsById[k]);

  if (filterCountEl) {
    filterCountEl.hidden = false;
    const newN = allResults.filter((j) => j.is_new).length;
    filterCountEl.textContent = `${jobs.length} offre(s) · ${newN} nouvelle(s) sur ${allResults.length}`;
  }

  if (!jobs.length) {
    resultsEl.innerHTML = `<article class="card"><p>Aucune offre avec ces filtres. Baissez le seuil de correspondance %.</p></article>`;
    return;
  }

  const groups = {};
  for (const job of jobs) {
    const key = job.tier_label || job.tier || "Offres";
    if (!groups[key]) groups[key] = [];
    groups[key].push(job);
  }

  const order = ["Maroc", "International"];
  const keys = Object.keys(groups).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });

  resultsEl.innerHTML = keys
    .map((key) => {
      const cards = groups[key]
        .map((job, index) => {
          const jobId = `${key}-${index}`;
          jobsById[jobId] = job;
          const meta = [
            job.city || job.location || "",
            job.contract_type || "",
            job.experience || "",
            job.salary || "",
            job.publication_date || "",
            job.remote ? "Télétravail" : "",
          ]
            .filter(Boolean)
            .join(" · ");
          const skills = (job.skills || []).slice(0, 8).join(", ");
          const pct = job.match_percent ?? job.score;
          const newBadge = job.is_new ? `<span class="badge-new">Nouveau</span>` : "";
          return `
        <article class="card" data-job-id="${escapeAttr(jobId)}">
          <div class="card-top">
            <div>
              <h2>${escapeHtml(job.title || "")}${newBadge}</h2>
              <p class="company">${escapeHtml(job.company || "")}</p>
            </div>
            <div class="score">${escapeHtml(String(pct ?? ""))} % de correspondance</div>
          </div>
          <p class="meta">${escapeHtml(meta)} · <span class="source">${escapeHtml(job.source || "")}</span></p>
          ${skills ? `<p class="meta">Compétences : ${escapeHtml(skills)}</p>` : ""}
          <p class="why"><strong>Pourquoi :</strong> ${escapeHtml((job.match_reasons || []).join("; "))}</p>
          ${job.llm_explanation ? `<p class="note">${escapeHtml(job.llm_explanation)}</p>` : ""}
          <a href="${escapeAttr(job.application_url || job.url || "#")}" target="_blank" rel="noopener">Postuler / Voir l’offre</a>
          <div class="actions">
            <button type="button" class="action-btn" data-action="cover_letter" data-job-id="${escapeAttr(jobId)}">Générer une lettre de motivation</button>
            <button type="button" class="action-btn" data-action="email" data-job-id="${escapeAttr(jobId)}">Générer un e-mail</button>
          </div>
        </article>`;
        })
        .join("");
      return `<section class="tier-block"><h3 class="tier-title">${escapeHtml(key)}</h3>${cards}</section>`;
    })
    .join("");

  resultsEl.querySelectorAll(".action-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const job = jobsById[btn.dataset.jobId] || {};
      openWriteModal(btn.dataset.action, job);
    });
  });
}

function openWriteModal(kind, job) {
  pendingKind = kind;
  pendingJob = job;
  modal.hidden = false;
  modalTitle.textContent =
    kind === "cover_letter" ? "Lettre de motivation" : "E-mail de candidature";
  modalJob.textContent = `${job.title || "Offre"} — ${job.company || ""}`;
  if (modalEditorMount) modalEditorMount.hidden = true;
  modalEditor?.clear();
  if (modalActions) modalActions.hidden = true;
  modalStatus.className = "hint";
  modalGenerate.disabled = false;
  if (modalPdf) modalPdf.hidden = false;
  hideCvMissingBanner();

  const file = resumeInput?.files?.[0] || savedResumeFile;
  if (file) {
    modalStatus.hidden = false;
    modalStatus.textContent = "Génération en cours…";
    modalGenerate.hidden = true;
    modalGenerate.textContent = "Régénérer";
    queueMicrotask(() => modalGenerate.click());
  } else {
    modalGenerate.hidden = false;
    modalGenerate.textContent = "Générer";
    modalStatus.hidden = true;
    modalStatus.textContent = "";
  }
}

function closeModal() {
  modal.hidden = true;
  hideCvMissingBanner();
  hidePdfContactError();
  pendingKind = null;
  pendingJob = null;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}
