"""Generate natural cover letters and application emails from CV + job offer."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from job_agent.linkedin import clean_company_name, clean_job_title
from job_agent.validators import is_valid_address, is_valid_email, is_valid_phone

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")
_SESSION_DEBUG_LOG = Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-8a6f5f.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "writing",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _session_dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "8a6f5f",
            "runId": "gen-quality",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        _SESSION_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _SESSION_DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


# #endregion


CONTACT_ADDRESS_PLACEHOLDER = "⚠️ Veuillez renseigner votre adresse complète."
CONTACT_PHONE_PLACEHOLDER = "⚠️ Veuillez renseigner votre numéro de téléphone."
CONTACT_EMAIL_PLACEHOLDER = "⚠️ Veuillez renseigner votre adresse e-mail."
# Field is present but fails format validation (not just empty — see job_agent.validators).
CONTACT_ADDRESS_INVALID = "⚠️ Veuillez renseigner une adresse complète valide."
CONTACT_PHONE_INVALID = "⚠️ Veuillez renseigner un numéro de téléphone valide."
CONTACT_EMAIL_INVALID = "⚠️ Veuillez renseigner une adresse e-mail valide."
_CONTACT_PLACEHOLDERS = frozenset(
    {
        CONTACT_ADDRESS_PLACEHOLDER,
        CONTACT_PHONE_PLACEHOLDER,
        CONTACT_EMAIL_PLACEHOLDER,
        CONTACT_ADDRESS_INVALID,
        CONTACT_PHONE_INVALID,
        CONTACT_EMAIL_INVALID,
    }
)

# Shown directly in the letter's contact block (not the export-blocking "⚠️ ..."
# warnings above) whenever a field is missing or invalid — see contact_block_lines().
CONTACT_ADDRESS_TAG = "[Adresse]"
CONTACT_PHONE_TAG = "[Numéro]"
CONTACT_EMAIL_TAG = "[Adresse e-mail]"

# A cover-letter date line, with or without the "Le " prefix (e.g. "15 juillet 2026"
# or "Le 15 Juillet 2026") — used to know where the candidate header block ends.
_COVER_LETTER_DATE_LINE = re.compile(r"(?i)^(?:le\s+)?\d{1,2}\s+[a-zéûôîà]+\s+\d{4}\b")


def generate_cover_letter(profile: dict[str, Any], job: dict[str, Any], resume_text: str = "") -> dict[str, Any]:
    """Return a print-ready French cover letter tailored to the offer + CV."""
    # #region agent log
    _dbg(
        "H1",
        "writing.py:generate_cover_letter",
        "start",
        {
            "title": (job.get("title") or "")[:80],
            "company": job.get("company"),
            "has_resume": bool(resume_text),
            "domain": profile.get("cv_domain"),
            "name": profile.get("name"),
        },
    )
    # #endregion
    contact = _candidate_contact(profile, resume_text)
    llm_text = _llm_write("cover_letter", profile, job, resume_text)
    if llm_text:
        plain = _inject_cover_letter_contacts(llm_text, contact)
        plain, html = _pack_document(plain, kind="cover_letter")
        # #region agent log
        _session_dbg(
            "A",
            "writing.py:generate_cover_letter",
            "engine chosen",
            {"engine": "llm", "kind": "cover_letter", "chars": len(plain), "has_key": _has_llm()},
        )
        # #endregion
        return {
            "ok": True,
            "kind": "cover_letter",
            "content": plain,
            "content_html": html,
            "engine": "llm",
        }
    plain = _inject_cover_letter_contacts(
        _template_cover_letter(profile, job, resume_text),
        contact,
    )
    plain, html = _pack_document(plain, kind="cover_letter")
    # #region agent log
    _session_dbg(
        "A",
        "writing.py:generate_cover_letter",
        "engine chosen",
        {
            "engine": "template",
            "kind": "cover_letter",
            "chars": len(plain),
            "has_key": _has_llm(),
            "first_line": plain.splitlines()[0][:120] if plain else "",
            "name": profile.get("name"),
        },
    )
    # #endregion
    return {
        "ok": True,
        "kind": "cover_letter",
        "content": plain,
        "content_html": html,
        "engine": "template",
    }


def _display_contact_field(value: str | None, is_valid: Any, placeholder: str) -> str:
    """Return ``value`` as-is when valid, otherwise the field's bracket placeholder."""
    candidate = (value or "").strip()
    if not candidate or candidate in _CONTACT_PLACEHOLDERS or "veuillez renseigner" in candidate.lower():
        return placeholder
    return candidate if is_valid(candidate) else placeholder


def contact_block_lines(contact: dict[str, str] | None) -> list[str]:
    """Return exactly 3 lines: address, phone, email.

    A field that is missing or fails its validator (job_agent.validators) is
    replaced by its bracket placeholder ([Adresse] / [Numéro] / [Adresse e-mail])
    instead of being silently dropped, so the header layout never loses a line
    and never shows a stray "⚠️ ..." warning inside the letter itself.
    """
    c = contact or {}
    return [
        _display_contact_field(c.get("address"), is_valid_address, CONTACT_ADDRESS_TAG),
        _display_contact_field(c.get("phone"), is_valid_phone, CONTACT_PHONE_TAG),
        _display_contact_field(c.get("email"), is_valid_email, CONTACT_EMAIL_TAG),
    ]


def _inject_cover_letter_contacts(text: str, contact: dict[str, str]) -> str:
    """Force Nom + known coords (no blanks between) atop the letter; never inject ⚠️."""
    name = (contact.get("name") or "Candidat").strip() or "Candidat"
    contacts = contact_block_lines(contact)
    raw = (text or "").strip()
    lines = raw.splitlines()
    i = 0
    if lines and lines[0].strip():
        i = 1  # drop existing name line
    while i < len(lines):
        ln = lines[i].strip()
        if not ln:
            i += 1
            continue
        low = ln.lower()
        if low.startswith("objet"):
            break
        if _COVER_LETTER_DATE_LINE.match(ln):
            break
        if re.search(r"(?i),\s*le\s+\d{1,2}\s+", ln):
            break
        # Strip legacy / LLM placeholder lines — never keep them in the letter
        if ln in _CONTACT_PLACEHOLDERS or "veuillez renseigner" in low or ln.startswith("⚠️"):
            i += 1
            continue
        if i <= 5 and (
            "@" in ln
            or re.search(r"(?:\+|0)\d", ln)
            or any(
                w in low
                for w in (
                    "rue",
                    "avenue",
                    "quartier",
                    "bd",
                    "boulevard",
                    "casablanca",
                    "rabat",
                    "maroc",
                    "morocco",
                )
            )
        ):
            i += 1
            continue
        if i <= 4 and not ln.endswith(",") and "madame" not in low and "monsieur" not in low:
            # leftover short header line (old contact / métier)
            i += 1
            continue
        break
    rest = "\n".join(lines[i:]).lstrip("\n")
    header = name + "\n" + "\n".join(contacts)
    return (header + "\n\n" + rest).strip() + "\n" if rest else header + "\n"


def _is_cover_letter_header_terminator(ln: str) -> bool:
    low = (ln or "").lower().strip()
    if not low:
        return False
    if low.startswith("objet"):
        return True
    if _COVER_LETTER_DATE_LINE.match(ln.strip()):
        return True
    if re.search(r"(?i),\s*le\s+\d{1,2}\s+", ln):
        return True
    if ln.strip().endswith(",") and any(
        w in low for w in ("madame", "monsieur", "bonjour", "chère", "cher")
    ):
        return True
    # Body paragraph — not a contact line
    if len(ln.strip()) > 100:
        return True
    if re.match(r"(?i)^(je |j’|nous |motivé|disponible)", low):
        return True
    return False


def _parse_cover_letter_contact_lines(text: str) -> tuple[str, str, str]:
    """Extract (address, phone, email) from letter header after the name."""
    lines = [(ln or "").strip() for ln in (text or "").splitlines()]
    i = 0
    while i < len(lines) and not lines[i]:
        i += 1
    if i >= len(lines):
        return "", "", ""
    i += 1  # skip name
    collected: list[str] = []
    while i < len(lines) and len(collected) < 3:
        ln = lines[i]
        i += 1
        if not ln:
            # Rich-text editor often inserts blank lines between <p>; skip them
            continue
        if _is_cover_letter_header_terminator(ln):
            break
        if ln in _CONTACT_PLACEHOLDERS or "veuillez renseigner" in ln.lower() or ln.startswith("⚠️"):
            continue
        collected.append(ln)

    address = phone = email = ""
    for item in collected:
        if "@" in item and not email:
            email = item
        elif re.search(r"\d", item) and not phone and "@" not in item:
            phone = item
        elif not address:
            address = item
    # Prefer strict order when we have exactly 3 lines
    if len(collected) == 3:
        address, phone, email = collected[0], collected[1], collected[2]
    return address, phone, email


def cover_letter_missing_contacts(text: str) -> list[str]:
    """Messages for contact fields that are missing OR fail format validation.

    A field only checked for emptiness would let through garbage like a phone
    number of "hello" or an address copied from the letter body. Each field is
    therefore also run through the matching validator in ``job_agent.validators``.
    """
    address, phone, email = _parse_cover_letter_contact_lines(text)
    errors: list[str] = []

    address = (address or "").strip()
    if not address:
        errors.append(CONTACT_ADDRESS_PLACEHOLDER)
    elif not is_valid_address(address):
        errors.append(CONTACT_ADDRESS_INVALID)

    phone = (phone or "").strip()
    if not phone:
        errors.append(CONTACT_PHONE_PLACEHOLDER)
    elif not is_valid_phone(phone):
        errors.append(CONTACT_PHONE_INVALID)

    email = (email or "").strip()
    if not email:
        errors.append(CONTACT_EMAIL_PLACEHOLDER)
    elif not is_valid_email(email):
        errors.append(CONTACT_EMAIL_INVALID)

    return errors


def cover_letter_contacts_ready(text: str) -> tuple[bool, str]:
    """Validate that address/phone/email are present AND well-formed.

    Returns ``(True, "")`` when the letter can safely be exported to PDF, or
    ``(False, errors)`` — one "⚠️ ..." message per line — otherwise. Export must
    be blocked whenever this returns False; the workflow itself is unchanged.
    """
    errors = cover_letter_missing_contacts(text)
    if errors:
        return False, "\n".join(errors)
    return True, ""


def generate_application_email(profile: dict[str, Any], job: dict[str, Any], resume_text: str = "") -> dict[str, Any]:
    """Return a short professional French application email."""
    job = _sanitize_job(job)
    # #region agent log
    _dbg(
        "H1",
        "writing.py:generate_application_email",
        "start",
        {
            "title": (job.get("title") or "")[:80],
            "company": job.get("company"),
            "has_resume": bool(resume_text),
        },
    )
    # #endregion
    llm_text = _llm_write("email", profile, job, resume_text)
    if llm_text:
        content = _ensure_email_subject(llm_text, profile, job, resume_text)
        plain, html = _pack_document(content)
        # #region agent log
        _session_dbg(
            "A",
            "writing.py:generate_application_email",
            "engine chosen",
            {
                "engine": "llm",
                "kind": "email",
                "chars": len(plain),
                "has_key": _has_llm(),
                "subject": plain.splitlines()[0][:120] if plain else "",
            },
        )
        # #endregion
        return {
            "ok": True,
            "kind": "email",
            "content": plain,
            "content_html": html,
            "engine": "llm",
        }
    plain, html = _pack_document(_template_email(profile, job, resume_text))
    # #region agent log
    _session_dbg(
        "A",
        "writing.py:generate_application_email",
        "engine chosen",
        {
            "engine": "template",
            "kind": "email",
            "chars": len(plain),
            "has_key": _has_llm(),
            "subject": plain.splitlines()[0][:120] if plain else "",
        },
    )
    # #endregion
    return {
        "ok": True,
        "kind": "email",
        "content": plain,
        "content_html": html,
        "engine": "template",
    }


def generate_linkedin_message(profile: dict[str, Any], job: dict[str, Any], resume_text: str = "") -> dict[str, Any]:
    """Return a short professional LinkedIn private/DM message (human, not robotic)."""
    job = _sanitize_job(job)
    # #region agent log
    _dbg(
        "H1",
        "writing.py:generate_linkedin_message",
        "start",
        {
            "title": (job.get("title") or "")[:80],
            "company": job.get("company"),
            "has_resume": bool(resume_text),
            "wants_dm": bool(job.get("wants_dm")),
        },
    )
    # #endregion
    llm_text = _llm_write("linkedin_dm", profile, job, resume_text)
    if llm_text:
        plain, html = _pack_document(llm_text)
        # #region agent log
        _session_dbg(
            "A",
            "writing.py:generate_linkedin_message",
            "engine chosen",
            {"engine": "llm", "kind": "linkedin_dm", "chars": len(plain), "has_key": _has_llm()},
        )
        # #endregion
        return {
            "ok": True,
            "kind": "linkedin_dm",
            "content": plain,
            "content_html": html,
            "engine": "llm",
        }
    plain, html = _pack_document(_template_linkedin_dm(profile, job, resume_text))
    # #region agent log
    _session_dbg(
        "A",
        "writing.py:generate_linkedin_message",
        "engine chosen",
        {"engine": "template", "kind": "linkedin_dm", "chars": len(plain), "has_key": _has_llm()},
    )
    # #endregion
    return {
        "ok": True,
        "kind": "linkedin_dm",
        "content": plain,
        "content_html": html,
        "engine": "template",
    }


def _sanitize_job(job: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(job or {})
    cleaned["title"] = clean_job_title(cleaned.get("title") or "")
    company = clean_company_name(cleaned.get("company") or "")
    cleaned["company"] = company or "entreprise"
    return cleaned


def _email_subject(
    profile: dict[str, Any],
    job: dict[str, Any],
    resume_text: str = "",
) -> str:
    """Clear subject: Candidature – Poste – Prénom Nom (from CV, never « Candidat »)."""
    contact = _candidate_contact(profile, resume_text)
    name = (contact.get("name") or "").strip()
    if name.lower() in {"candidat", "candidate", "cv", "utilisateur", "user"}:
        name = ""
    job_title = clean_job_title(job.get("title") or "Poste")
    # Drop trailing city junk often glued to LinkedIn titles
    job_title = re.sub(
        r"(?i)\s*[–\-—,]\s*(casablanca|rabat|marrakech|tanger|f[eè]s|agadir|maroc|morocco)\s*$",
        "",
        job_title,
    ).strip(" –-")
    if name:
        return f"Objet : Candidature – {job_title} – {name}"
    return f"Objet : Candidature – {job_title}"


def _ensure_email_subject(
    text: str,
    profile: dict[str, Any],
    job: dict[str, Any],
    resume_text: str = "",
) -> str:
    """Force a short professional subject; never keep post dump / hashtags in Objet."""
    subject = _email_subject(profile, job, resume_text)
    body = (text or "").strip()
    if re.match(r"(?i)^objet\s*:", body):
        # Drop the LLM subject line (often polluted with post text)
        parts = body.split("\n", 1)
        body = parts[1].lstrip("\n") if len(parts) > 1 else ""
    return f"{subject}\n\n{body}".strip() + "\n"


def _has_llm() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _llm_write(kind: str, profile: dict[str, Any], job: dict[str, Any], resume_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    # #region agent log
    _session_dbg(
        "A",
        "writing.py:_llm_write:entry",
        "llm gate",
        {
            "kind": kind,
            "has_key": bool(api_key),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        },
    )
    # #endregion
    if not api_key:
        return ""

    try:
        from openai import OpenAI
    except ImportError:
        # #region agent log
        _session_dbg("B", "writing.py:_llm_write", "openai import missing", {"kind": kind})
        # #endregion
        return ""

    name = _candidate_contact(profile, resume_text).get("name") or "Candidat"
    titles = ", ".join(profile.get("titles") or [])[:120]
    skills = ", ".join(profile.get("skills") or [])[:200]
    cv_excerpt = (resume_text or "")[:2500]
    job = _sanitize_job(job)
    job_title = job.get("title") or "le poste"
    company = job.get("company") or "votre entreprise"
    city = job.get("city") or job.get("location") or ""
    description = (job.get("description") or "")[:800]
    subject = _email_subject(profile, job, resume_text)

    recruiter = (job.get("recruiter") or "").strip()

    if kind == "cover_letter":
        greeting = _cover_letter_greeting(job)
        contact = _candidate_contact(profile, resume_text)
        today = _format_french_date()
        coords = contact_block_lines(contact)
        coords_block = ("\n".join(coords) + "\n") if coords else "(aucune — omettre adresse/tél/email)\n"
        contact_hint = (
            f"Identité CV (OBLIGATOIRE — ne pas inventer d’autre nom): "
            f"nom={contact.get('name')}, métier={contact.get('headline')}.\n"
            f"Coordonnées connues à coller sous le nom (sans ligne vide entre elles) :\n"
            f"{coords_block}"
            f"N’invente PAS d’adresse/tél/email. N’écris JAMAIS « ⚠️ » ni « Veuillez renseigner ». "
            f"Si une coordonnée manque, omets-la.\n"
            f"Date à utiliser: {today}\n"
        )
        source_hint = (
            "via un post LinkedIn"
            if (job.get("source") or "").lower() == "linkedin"
            else "via une offre d’emploi en ligne"
        )
        system = (
            "Tu rédiges des lettres de motivation en français, prêtes à imprimer ou envoyer. "
            "Sortie en TEXTE BRUT uniquement (pas de markdown, pas de listes à puces, pas de HTML). "
            "Mise en page professionnelle, bien espacée.\n\n"
            "Structure OBLIGATOIRE exactement dans cet ordre (ne rien ajouter, ne rien inverser):\n"
            "1) Nom Prénom (première ligne seule — sera affichée en titre gras)\n"
            "2) Adresse complète (si connue uniquement)\n"
            "3) Téléphone (si connu, ligne suivante sans vide)\n"
            "4) Email (si connu, ligne suivante sans vide)\n"
            "   INTERDIT d’écrire des messages ⚠️ / « Veuillez renseigner… » dans la lettre.\n"
            "5) ligne vide\n"
            "6) Date (ex: Le 15 Juillet 2026) — sans en-tête destinataire entreprise\n"
            "7) ligne vide\n"
            "8) Objet : Candidature au poste de …\n"
            "9) ligne vide\n"
            "10) Formule de politesse (ex: Madame, Monsieur, / Chère Madame, / Monsieur,)\n"
            "11) ligne vide\n"
            "12) PARAGRAPHE 1 — Pourquoi cette entreprise ? Ce qui t’intéresse chez eux. "
            "Le poste demandé.\n"
            "13) ligne vide\n"
            "14) PARAGRAPHE 2 — Ton parcours : formation, expériences, compétences, "
            "résultats obtenus (faits du CV uniquement).\n"
            "15) ligne vide\n"
            "16) PARAGRAPHE 3 — Ce que tu peux apporter, motivation, valeur ajoutée "
            "pour ce poste / cette entreprise.\n"
            "17) ligne vide\n"
            "18) PARAGRAPHE DE CONCLUSION — Disponibilité pour un entretien, "
            "remerciements, formule de politesse finale courte.\n"
            "19) ligne vide\n"
            "20) Cordialement,\n"
            "21) ligne vide\n"
            "22) Nom Prénom\n\n"
            "INTERDIT: bloc destinataire (Service RH / entreprise), ligne « Métier » "
            "sous le nom, formule « Je vous prie d’agréer… ». "
            "Utilise UNIQUEMENT le nom et les coordonnées fournis depuis le CV. "
            "N’invente rien hors du CV. ~300–420 mots pour le corps (hors en-tête)."
        )
        user = (
            f"Rédige une lettre de motivation complète pour {name}.\n"
            f"Formule d’appel: {greeting}\n"
            f"{contact_hint}"
            f"Intitulés CV: {titles}\nCompétences: {skills}\n"
            f"Extrait CV:\n{cv_excerpt}\n\n"
            f"Offre: {job_title} chez {company}"
            f"{f' ({city})' if city else ''}.\n"
            f"Source: {source_hint}.\n"
            f"Description:\n{description}\n\n"
            "Respecte strictement la structure: en-tête candidat + date + objet + "
            "politesse + 3 paragraphes + conclusion + Cordialement."
        )
        max_tokens = 950
    elif kind == "linkedin_dm":
        greeting = _dm_greeting(job)
        top_skills = ", ".join((profile.get("skills") or [])[:3]) or skills
        company_ref = company if company.lower() != "entreprise" else ""
        wants_dm = bool(job.get("wants_dm"))
        objective = (
            "postuler à l’offre du post et proposer l’envoi du CV ou un court échange"
            if wants_dm
            else "postuler / établir un premier contact et proposer l’envoi du CV"
        )
        system = (
            "Tu rédiges des messages privés professionnels (LinkedIn) en français. "
            "80 à 150 mots, naturel, humain, personnalisé, sans phrases robotiques. "
            "Pas de markdown ni de lettre de motivation collée.\n\n"
            "Structure: salutation → présentation → raison → valeur (1–2 phrases) → "
            "appel à l’action clair → remerciement + signature.\n"
            f"Utilise le nom exact du candidat: {name}."
        )
        user = (
            f"Rédige un message privé pour {name}.\n"
            f"Salutation: {greeting}\n"
            f"Objectif: {objective}.\n"
            f"Intitulés CV: {titles}\n"
            f"Compétences (1–2 max): {top_skills}\n"
            f"Extrait CV:\n{cv_excerpt}\n\n"
            f"Poste: {job_title}\nEntreprise: {company_ref or 'non précisée'}\n"
            f"Recruteur: {recruiter or 'non précisé'}\n"
            f"Contexte:\n{description}\n\n"
            "80–150 mots, avec un appel à l’action à la fin."
        )
        max_tokens = 320
    else:
        # Application email
        greeting = _email_greeting(job)
        contact = _candidate_contact(profile, resume_text)
        contact_hint = (
            "Coordonnées pour la signature (depuis le CV): "
            f"nom={contact.get('name')}, "
            f"email={contact.get('email') or 'N/A'}, "
            f"tél={contact.get('phone') or 'N/A'}, "
            f"LinkedIn={contact.get('linkedin') or 'N/A'}.\n"
        )
        source_hint = (
            "via un post LinkedIn"
            if (job.get("source") or "").lower() == "linkedin"
            else "via une offre d’emploi en ligne"
        )
        top_skills = ", ".join((profile.get("skills") or [])[:4]) or skills
        system = (
            "Tu rédiges des e-mails de candidature en français, simples, professionnels et humains. "
            "Premier contact avec le recruteur : clair, personnalisé, qui donne envie d’ouvrir le CV. "
            "100 à 180 mots max pour le corps. Pas de markdown, pas de listes à puces.\n\n"
            "Structure OBLIGATOIRE:\n"
            "1) Salutation: Bonjour Madame, / Bonjour Monsieur, / Bonjour Madame, Monsieur, "
            "(ou le titre + nom du recruteur si fourni).\n"
            "2) Introduction directe: poste visé + où l’offre a été trouvée.\n"
            "3) Présentation concise (2–3 phrases): profil, expérience/formation, principal atout "
            "avec idéalement un exemple concret lié au poste.\n"
            "4) Motivation sincère: pourquoi ce poste/cette entreprise + ce que tu apportes "
            "(sans inventer d’actualité).\n"
            "5) Conclusion: CV joint (et lettre si utile), disponibilité pour un entretien, remerciements.\n"
            "6) Formule de politesse courte (Bien cordialement,) puis signature complète: "
            "nom, téléphone, e-mail, LinkedIn si connu.\n\n"
            "N’INCLUS PAS de ligne Objet (ajoutée séparément). "
            "N’utilise jamais le texte brut du post LinkedIn ni les hashtags. "
            "Ne copie pas une lettre de motivation dans le mail. "
            "Ton naturel, jamais familier ni trop corporate. "
            "N’invente rien hors du CV."
        )
        user = (
            f"Rédige le corps d’un e-mail de candidature pour {name}.\n"
            f"Objet imposé (ne pas le réécrire): {subject}\n"
            f"Salutation à utiliser: {greeting}\n"
            f"{contact_hint}"
            f"Intitulés CV: {titles}\n"
            f"Compétences pertinentes à privilégier (1–2 max dans le mail): {top_skills}\n"
            f"Extrait CV:\n{cv_excerpt}\n\n"
            f"Poste: {job_title}\nEntreprise: {company}\nVille: {city}\n"
            f"Source de l’offre: {source_hint}.\n"
            f"Contexte de l’offre (inspirations, ne pas coller tel quel):\n{description}\n\n"
            "Personnalise pour cette entreprise. Sois concis (100–180 mots). "
            "Mentionne clairement que le CV est joint."
        )
        max_tokens = 420

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        text = (response.choices[0].message.content or "").strip()
        # #region agent log
        _dbg("H2", "writing.py:_llm_write", "llm ok", {"kind": kind, "chars": len(text)})
        _session_dbg(
            "B",
            "writing.py:_llm_write",
            "llm ok",
            {"kind": kind, "chars": len(text), "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini")},
        )
        # #endregion
        return text
    except Exception as exc:  # noqa: BLE001
        # #region agent log
        _dbg("H2", "writing.py:_llm_write", "llm failed", {"kind": kind, "error": str(exc)[:160]})
        _session_dbg(
            "B",
            "writing.py:_llm_write",
            "llm failed",
            {"kind": kind, "error": str(exc)[:160]},
        )
        # #endregion
        return ""


def _template_cover_letter(profile: dict[str, Any], job: dict[str, Any], resume_text: str) -> str:
    job = _sanitize_job(job)
    contact = _candidate_contact(profile, resume_text)
    name = contact["name"]
    headline = contact["headline"] or (profile.get("titles") or ["Professionnel"])[0]
    skills = ", ".join((profile.get("skills") or [])[:6]) or "mes compétences techniques"
    job_title = job.get("title") or "le poste proposé"
    company = job.get("company") or "votre entreprise"
    company_ref = "" if company.lower() == "entreprise" else company
    city = job.get("city") or job.get("location") or ""
    greeting = _cover_letter_greeting(job)
    highlight = _pick_highlight(resume_text, profile)
    formation = _pick_formation(resume_text)
    source = (
        "via un post LinkedIn"
        if (job.get("source") or "").lower() == "linkedin"
        else "via une offre d’emploi"
    )
    body_company = company_ref or "votre entreprise"
    today = _format_french_date()

    sender_lines = [name, *contact_block_lines(contact)]

    # P1 — entreprise / intérêt / poste
    p1 = (
        f"Je souhaite postuler au poste de {job_title} au sein de {body_company}"
        f"{f', à {city}' if city else ''}. "
        f"J’ai découvert cette opportunité {source} et elle retient particulièrement mon attention "
        f"parce que le périmètre du poste correspond à mon orientation professionnelle "
        f"et à ce que je recherche aujourd’hui."
    )

    # P2 — parcours / formation / expériences / compétences / résultats
    formation_bit = f" Ma formation ({formation}) nourrit ce parcours." if formation else ""
    p2 = (
        f"En tant que {headline}, j’ai développé une approche concrète et structurée."
        f"{formation_bit} "
        f"{highlight} "
        f"Parmi les compétences que je mobilise : {skills}."
    )

    # P3 — apport / motivation / valeur ajoutée
    p3 = (
        f"Ce que je peux apporter à {body_company}, c’est une contribution opérationnelle "
        f"dès les premières semaines, avec sérieux, autonomie et un vrai souci du résultat. "
        f"Je suis motivé(e) par ce poste car il me permettrait d’apporter une valeur ajoutée "
        f"directe à vos équipes, en m’appuyant sur mon expérience et mes compétences."
    )

    # Conclusion — disponibilité / remerciements / politesse
    conclusion = (
        "Je reste disponible pour un entretien à votre convenance afin d’échanger sur vos attentes. "
        "Je vous remercie par avance de l’attention portée à ma candidature."
    )

    return (
        "\n".join(sender_lines)
        + "\n\n"
        + f"{today}\n\n"
        + f"Objet : Candidature au poste de {job_title}\n\n"
        + f"{greeting}\n\n"
        + f"{p1}\n\n"
        + f"{p2}\n\n"
        + f"{p3}\n\n"
        + f"{conclusion}\n\n"
        + "Cordialement,\n\n"
        + f"{name}\n"
    )


def _pick_formation(resume_text: str) -> str:
    """Best-effort short formation snippet from CV text."""
    raw = resume_text or ""
    if not raw:
        return ""
    # Prefer a line under a Formation / Éducation heading
    section = re.search(
        r"(?is)(?:^|\n)\s*(?:formation(?:s)?|éducation|education|dipl[oô]mes?)\s*[:\n]+(.{20,220})",
        raw,
    )
    if section:
        chunk = re.sub(r"\s+", " ", section.group(1)).strip(" .-–|:;")
        # Stop before next section-looking word
        chunk = re.split(
            r"(?i)\b(?:expérience|experience|compétences|skills|projets|langues)\b",
            chunk,
            maxsplit=1,
        )[0].strip(" .-–")
        if 15 <= len(chunk) <= 120:
            return chunk
        if chunk:
            return chunk[:117].rsplit(" ", 1)[0] + "…"
    # Fallback: diploma keywords in a short line
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" .-–")
        if not (20 <= len(line) <= 110):
            continue
        if re.search(
            r"(?i)\b(?:master|licence|bachelor|dut|bts|ingénieur|engineer|dipl[oô]me|bac\s*\+\s*\d)\b",
            line,
        ):
            return line
    return ""


def _cover_letter_greeting(job: dict[str, Any]) -> str:
    recruiter = (job.get("recruiter") or "").strip()
    if not recruiter:
        return "Madame, Monsieur,"
    # Prefer first name for LinkedIn recruiters when it looks like a person name
    parts = recruiter.split()
    if 1 <= len(parts) <= 3 and recruiter[0].isupper():
        return f"Madame, Monsieur {parts[-1]}," if len(parts) >= 2 else f"Bonjour {parts[0]},"
    return "Madame, Monsieur,"


def _email_greeting(job: dict[str, Any]) -> str:
    """Professional email salutation."""
    recruiter = (job.get("recruiter") or "").strip()
    if not recruiter:
        return "Bonjour Madame, Monsieur,"
    parts = recruiter.split()
    if not (1 <= len(parts) <= 3 and recruiter[0].isupper()):
        return "Bonjour Madame, Monsieur,"
    # Avoid guessing Madame vs Monsieur from a first name alone
    if len(parts) == 1:
        return f"Bonjour {parts[0]},"
    return f"Bonjour Madame, Monsieur {parts[-1]},"


def _dm_greeting(job: dict[str, Any]) -> str:
    """LinkedIn / private-message salutation."""
    recruiter = (job.get("recruiter") or "").strip()
    if not recruiter:
        return "Bonjour Madame, Monsieur,"
    parts = recruiter.split()
    if not (1 <= len(parts) <= 4 and recruiter[0].isupper()):
        return "Bonjour Madame, Monsieur,"
    # Prefer first name when available (common on LinkedIn)
    first = parts[0]
    if first.lower() in {"m", "mme", "mr", "mrs", "ms", "dr"}:
        return f"Bonjour {' '.join(parts)},"
    return f"Bonjour {first},"


def _extract_contact_bits(resume_text: str) -> dict[str, str]:
    text = resume_text or ""
    email_m = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    phone_m = re.search(
        r"(?:\+\d{1,3}[\s\-.]*)?(?:\(?0?\d{1,3}\)?[\s\-.]*)?\d{1,2}(?:[\s\-.]?\d{2}){3,4}",
        text,
    )
    phone = ""
    if phone_m:
        phone = re.sub(r"\s+", " ", phone_m.group(0)).strip()
        near = re.search(r"\+\d{1,3}[\s\-.]*(?:\d[\s\-.]*){8,12}", text)
        if near:
            phone = re.sub(r"\s+", " ", near.group(0)).strip()
    linkedin_m = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%À-ÿ]+/?",
        text,
        flags=re.I,
    )
    linkedin = ""
    if linkedin_m:
        linkedin = linkedin_m.group(0).strip()
        if not linkedin.lower().startswith("http"):
            linkedin = "https://" + linkedin.lstrip("/")
    return {
        "email": email_m.group(0).strip() if email_m else "",
        "phone": phone,
        "linkedin": linkedin,
    }


def _guess_place_from_profile(profile: dict[str, Any]) -> str:
    locs = profile.get("locations") or []
    if locs:
        return str(locs[0]).strip()
    return ""


def _format_french_date(today: date | None = None) -> str:
    """Return e.g. "Le 15 Juillet 2026": "Le " + day + Month (leading capital only) + year."""
    months = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    d = today or date.today()
    month = months[d.month - 1]
    return f"Le {d.day} {month[:1].upper()}{month[1:]} {d.year}"


def _format_cover_letter_header(contact: dict[str, str], today: str | None = None) -> str:
    """Candidate header matching the official letter layout (name + coords + date)."""
    name = (contact.get("name") or "Candidat").strip()
    lines = [name, *contact_block_lines(contact), "", today or _format_french_date()]
    return "\n".join(lines)


def _template_email(profile: dict[str, Any], job: dict[str, Any], resume_text: str) -> str:
    job = _sanitize_job(job)
    contact = _candidate_contact(profile, resume_text)
    name = contact["name"]
    title = contact.get("headline") or (profile.get("titles") or ["professionnel IT"])[0]
    skills = ", ".join((profile.get("skills") or [])[:3]) or "mon expérience"
    job_title = job.get("title") or "le poste"
    company = job.get("company") or "votre entreprise"
    company_ref = "" if company.lower() == "entreprise" else company
    highlight = _pick_highlight(resume_text, profile)
    subject = _email_subject(profile, job, resume_text)
    greeting = _email_greeting(job)
    signature = _format_email_signature(name, contact)
    source = (
        "via un post LinkedIn"
        if (job.get("source") or "").lower() == "linkedin"
        else "via une offre d’emploi"
    )

    return (
        f"{subject}\n\n"
        f"{greeting}\n\n"
        f"Je vous contacte concernant le poste de {job_title}"
        f"{f' chez {company_ref}' if company_ref else ''}, que j’ai découvert {source}.\n\n"
        f"Je suis {title}. {highlight} "
        f"Parmi les compétences directement utiles pour ce poste : {skills}.\n\n"
        f"Ce poste m’intéresse car il me permettrait de contribuer concrètement "
        f"à vos besoins"
        f"{f' au sein de {company_ref}' if company_ref else ''}, "
        f"avec un profil opérationnel et orienté résultats.\n\n"
        f"Vous trouverez mon CV en pièce jointe. Je reste à votre disposition "
        f"pour un entretien et vous remercie par avance de votre attention.\n\n"
        f"Cordialement,\n\n"
        f"{signature}\n"
    )


def _format_email_signature(name: str, contact: dict[str, str]) -> str:
    lines = [name]
    if contact.get("phone"):
        lines.append(contact["phone"])
    if contact.get("email"):
        lines.append(contact["email"])
    if contact.get("linkedin"):
        lines.append(contact["linkedin"])
    return "\n".join(lines)


def _template_linkedin_dm(profile: dict[str, Any], job: dict[str, Any], resume_text: str) -> str:
    job = _sanitize_job(job)
    contact = _candidate_contact(profile, resume_text)
    name = contact["name"]
    title = contact.get("headline") or (profile.get("titles") or ["professionnel IT"])[0]
    skills = ", ".join((profile.get("skills") or [])[:2]) or "mon parcours"
    job_title = job.get("title") or "le poste"
    company = job.get("company") or "votre équipe"
    company_ref = "" if company.lower() == "entreprise" else company
    greeting = _dm_greeting(job)
    highlight = _pick_highlight(resume_text, profile)
    if len(highlight) > 180:
        highlight = highlight[:177].rsplit(" ", 1)[0] + "."

    company_bit = f" chez {company_ref}" if company_ref else ""
    return (
        f"{greeting}\n\n"
        f"Je m’appelle {name}, {title}. "
        f"Je vous écris au sujet du poste de {job_title}{company_bit}, "
        f"qui correspond bien à mon domaine d’expertise.\n\n"
        f"{highlight} "
        f"Compétences utiles ici : {skills}.\n\n"
        f"Si mon profil vous semble pertinent, je peux vous envoyer mon CV "
        f"ou échanger quelques minutes à votre convenance.\n\n"
        f"Merci pour votre temps,\n"
        f"{name}\n"
    )


def _pick_highlight(resume_text: str, profile: dict[str, Any]) -> str:
    """One concrete, positive example — complements the CV instead of copying it."""
    domain = (profile.get("cv_domain") or "").lower()
    text = (resume_text or "").lower()
    titles = " ".join(profile.get("titles") or []).lower()
    raw = resume_text or ""

    # Prefer a sentence that contains a measurable result
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", raw):
        sentence = re.sub(r"\s+", " ", sentence).strip(" .,-–")
        if not (40 <= len(sentence) <= 180):
            continue
        if not re.search(
            r"\b\d+\s*(?:%|pour\s*cent)|(?:réduit|amélioré|augmenté|géré|mis en place|développé)",
            sentence,
            flags=re.I,
        ):
            continue
        # Drop truncated junk / titles alone
        if sentence.lower().startswith(("windows", "active directory", "microsoft")):
            continue
        example = sentence[0].lower() + sentence[1:] if sentence else sentence
        return (
            f"Par exemple, {example}. "
            "Ce type de résultat illustre ma façon d’apporter une valeur concrète."
        )

    if domain == "it_admin" or "administrateur" in titles:
        if "active directory" in text or "windows server" in text:
            return (
                "Lors de précédentes missions, j’ai notamment contribué à l’administration "
                "des comptes, des serveurs et à la continuité de service au quotidien, "
                "avec un suivi rigoureux des incidents."
            )
        return (
            "Au fil de mon expérience support et systèmes, j’ai appris à diagnostiquer "
            "rapidement, documenter les actions et stabiliser l’environnement de travail "
            "des utilisateurs."
        )
    if "python" in text or "développ" in text or domain == "software":
        return (
            "Sur mes derniers projets, j’ai contribué à concevoir et fiabiliser "
            "des solutions techniques en restant proche des besoins métier, "
            "plutôt que de me limiter à une liste d’outils."
        )
    return (
        "Mon parcours m’a appris à avancer de façon structurée sur les sujets confiés, "
        "à prioriser l’impact concret pour l’équipe, et à rendre compte clairement des résultats."
    )


def _candidate_contact(profile: dict[str, Any], resume_text: str = "") -> dict[str, str]:
    """Identity for writing: always from the CV text, never static profile leftovers."""
    from job_agent.resume import extract_contact_fields, _guess_name

    raw = extract_contact_fields(resume_text or "")
    guessed = _guess_name(resume_text or "")
    profile_name = (profile.get("name") or "").strip()
    # Generic placeholder labels only — never a hardcoded person's name. A CV's own
    # guessed name always wins via the token-count check below regardless of what
    # (if anything) is statically configured in profile.json.
    placeholders = {
        "",
        "candidat",
        "candidate",
        "cv",
        "curriculum vitae",
        "resume",
        "utilisateur",
        "user",
    }
    # Prefer CV-extracted name whenever profile name is missing / placeholder / shorter
    if guessed and (
        profile_name.lower() in placeholders
        or len(guessed.split()) >= len(profile_name.split())
    ):
        name = guessed
    else:
        name = profile_name or guessed or "Candidat"
    headline = (
        (profile.get("headline") or "").strip()
        or raw.get("headline")
        or ((profile.get("titles") or [""])[0] or "").strip()
        or "Professionnel"
    )
    return {
        "name": name,
        "headline": headline,
        "email": (profile.get("email") or raw.get("email") or "").strip(),
        "phone": (profile.get("phone") or raw.get("phone") or "").strip(),
        "address": (profile.get("address") or raw.get("address") or "").strip(),
        "linkedin": (profile.get("linkedin") or raw.get("linkedin") or "").strip(),
    }


def _pack_document(text: str, kind: str = "") -> tuple[str, str]:
    """Return (plain_text, rich_html) for the editor."""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    if re.search(r"<(?:p|div|br|strong|em|ul|ol|h1)\b", raw, flags=re.I):
        html = raw
        plain = html_to_plain(html)
    else:
        plain = raw
        html = (
            cover_letter_to_rich_html(plain)
            if kind == "cover_letter"
            else plain_to_rich_html(plain)
        )
    return plain, html


def cover_letter_to_rich_html(text: str) -> str:
    """Convert cover letter plain text: first line = H1 (bold, large)."""
    import html as html_lib

    raw = (text or "").strip()
    if not raw:
        return "<p></p>"
    lines = raw.splitlines()
    # First non-empty line = candidate name (H1)
    name_idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    parts: list[str] = []
    if name_idx is not None:
        name = lines[name_idx].strip()
        parts.append(f"<h1><strong>{html_lib.escape(name)}</strong></h1>")
        rest = "\n".join(lines[name_idx + 1 :]).lstrip("\n")
    else:
        rest = raw
    if rest.strip():
        parts.append(plain_to_rich_html(rest))
    return "".join(parts) or "<p></p>"


def plain_to_rich_html(text: str) -> str:
    """Convert a plain letter/email into simple rich-text paragraphs."""
    import html as html_lib

    blocks = re.split(r"\n\s*\n", (text or "").strip())
    parts: list[str] = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines()]
        if not any(lines):
            continue
        if len(lines) == 1:
            parts.append(f"<p>{html_lib.escape(lines[0])}</p>")
        else:
            inner = "<br>".join(html_lib.escape(ln) for ln in lines)
            parts.append(f"<p>{inner}</p>")
    return "".join(parts) or "<p></p>"


def html_to_plain(html: str) -> str:
    text = html or ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</h1\s*>", "\n\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</div\s*>", "\n", text)
    text = re.sub(r"(?i)</li\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    import html as html_lib

    return html_lib.unescape(text).strip()


_REWRITE_ACTIONS: dict[str, str] = {
    "more_professional": "Rends le texte plus professionnel et soigné, sans le rendre froid.",
    "more_human": "Rends le texte plus humain et naturel, comme écrit par une vraie personne.",
    "shorter": "Raccourcis nettement le texte en gardant l’essentiel.",
    "more_convincing": "Rends le texte plus convaincant avec des formulations plus percutantes.",
    "more_polite": "Rends le texte plus poli et courtois.",
    "more_dynamic": "Rends le ton plus dynamique et engageant.",
    "fix_spelling": "Corrige uniquement l’orthographe, sans changer le sens ni la structure.",
    "fix_grammar": "Corrige la grammaire et la syntaxe, sans changer le message.",
    "rephrase": "Reformule le texte avec d’autres mots, même idée.",
    "simplify": "Simplifie le vocabulaire et les phrases.",
    "add_details": "Ajoute quelques détails concrets utiles (sans inventer de faits absents du texte).",
    "remove_repetitions": "Supprime les répétitions et allège le style.",
    "adapt_job": "Adapte davantage le texte au poste indiqué dans le contexte.",
    "adapt_sector": "Adapte le vocabulaire au secteur indiqué dans le contexte.",
    "adapt_experience": "Adapte le niveau de discours à l’expérience du candidat.",
}


def rewrite_document(
    content: str,
    *,
    action: str,
    kind: str = "cover_letter",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rewrite letter/email/DM according to an improvement action."""
    instruction = _REWRITE_ACTIONS.get(action)
    if not instruction:
        raise ValueError("Action d’amélioration inconnue.")

    plain = html_to_plain(content) if "<" in (content or "") else (content or "").strip()
    if not plain:
        raise ValueError("Aucun texte à améliorer.")

    ctx = context or {}
    kind_label = {
        "cover_letter": "lettre de motivation",
        "email": "e-mail de candidature",
        "linkedin_dm": "message privé LinkedIn",
    }.get(kind, "document")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        improved = plain
        if action == "shorter":
            paras = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
            improved = "\n\n".join(paras[: max(2, len(paras) - 1)]) if len(paras) > 2 else plain
        elif action == "remove_repetitions":
            lines = []
            seen: set[str] = set()
            for line in plain.splitlines():
                key = re.sub(r"\s+", " ", line.strip().lower())
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                lines.append(line)
            improved = "\n".join(lines)
        plain_out, html_out = _pack_document(improved, kind=kind)
        return {
            "ok": True,
            "content": plain_out,
            "content_html": html_out,
            "engine": "template",
            "action": action,
        }

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ValueError("Module OpenAI indisponible.") from exc

    structure_hint = ""
    if kind == "cover_letter":
        structure_hint = (
            "Conserve STRICTEMENT la structure: Nom + adresse/tél/email + Date + Objet + "
            "formule de politesse + 3 paragraphes (entreprise / parcours / apport) + "
            "conclusion (disponibilité + remerciements) + Cordialement + Nom. "
            "Ne rajoute pas de bloc destinataire RH."
        )

    system = (
        f"Tu améliores des {kind_label} en français. "
        "Conserve la structure utile (objet, salutation, signature si présents). "
        f"{structure_hint} "
        "Pas de markdown. Texte prêt pour un éditeur riche. "
        "N’invente pas de faits absents du texte d’origine."
    )
    user = (
        f"Action: {instruction}\n"
        f"Poste: {ctx.get('title') or ''}\n"
        f"Entreprise: {ctx.get('company') or ''}\n\n"
        f"Texte actuel:\n{plain}\n\n"
        "Renvoie uniquement le texte amélioré."
    )
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=900,
        temperature=0.5,
    )
    improved = (response.choices[0].message.content or "").strip()
    if not improved:
        raise ValueError("L’amélioration n’a renvoyé aucun texte.")
    plain_out, html_out = _pack_document(improved, kind=kind)
    return {
        "ok": True,
        "content": plain_out,
        "content_html": html_out,
        "engine": "llm",
        "action": action,
    }
