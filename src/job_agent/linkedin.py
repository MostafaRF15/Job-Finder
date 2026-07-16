"""Analyze pasted LinkedIn job posts against a CV and prepare generation context."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import requests

from job_agent.scoring import score_jobs

_LINKEDIN_HOSTS = {
    "linkedin.com",
    "www.linkedin.com",
    "lnkd.in",
    "www.lnkd.in",
}

_ROLE_MARKERS = (
    "développeur",
    "developpeur",
    "administrateur",
    "engineer",
    "ingénieur",
    "ingenieur",
    "technicien",
    "consultant",
    "analyst",
    "specialist",
    "spécialiste",
    "support",
    "helpdesk",
    "help desk",
    "manager",
    "stage",
    "alternance",
    "administrateur",
)

# Soft words alone (opportunité, contactez-moi…) are NOT enough to count as a job post.
_HARD_JOB_WORDS = (
    "recrut",
    "hiring",
    "we are hiring",
    "looking for",
    "poste",
    "offre d",
    "offre :",
    "offre:",
    "candidat",
    "profil recherch",
    "profil :",
    "mission",
    "compétence",
    "competence",
    "expérience",
    "experience",
    "cdi",
    "cdd",
    "freelance",
    "télétravail",
    "teletravail",
    "remote",
    "hybride",
    "hybrid",
    "salaire",
    "salary",
    "postuler",
    "responsabilit",
    "prérequi",
    "prerequi",
    "qualification",
)

_CTA_ONLY_RE = re.compile(
    r"(?i)"
    r"(?:contactez[- ]?moi(?:\s+directement)?"
    r"|envoyez[- ]?moi\s+un\s+message"
    r"|messagez[- ]?moi"
    r"|partagez\s+(?:cette\s+)?(?:opportunit[eé]|annonce|offre)"
    r"|partagez\s+avec\s+votre\s+r[eé]seau"
    r"|avec\s+votre\s+r[eé]seau"
    r"|en\s+(?:mp|dm)"
    r"|dm\s+me"
    r"|inbox"
    r"|message\s+priv[eé])"
)

_URL_ONLY_PASTE_MSG = (
    "En mode « Texte collé », un lien seul ne suffit pas. "
    "Collez le contenu du post LinkedIn (comme sur LinkedIn), "
    "ou basculez sur « URL du post »."
)

_WEAK_PASTE_MSG = (
    "Impossible d’identifier une offre dans ce texte. "
    "Collez le texte complet du post LinkedIn "
    "(intitulé du poste, entreprise, missions…), "
    "pas seulement une phrase courte ou un appel à contacter / partager."
)


def resolve_post_input(post: str = "", url: str = "") -> tuple[str, str]:
    """Resolve pasted text and/or LinkedIn URL into post body + optional source URL."""
    post = normalize_post_text(post or "")
    url = (url or "").strip()

    if url:
        fetched = normalize_post_text(fetch_linkedin_post_text(url))
        if post and post not in fetched:
            text = f"{fetched}\n\n{post}".strip() if fetched else post
        else:
            text = fetched or post
        if not text:
            raise ValueError(
                "Impossible de lire ce lien LinkedIn (accès limité). "
                "Collez le texte du post à la place."
            )
        validate_job_post_text(text, pasted_only=False)
        return text, url

    if not post:
        raise ValueError("Collez le texte du post, ou saisissez l’URL LinkedIn.")
    validate_job_post_text(post, pasted_only=True)
    return post, ""


def validate_job_post_text(text: str, *, pasted_only: bool = False) -> None:
    """Reject empty / URL-only / CTA-only / content-poor inputs that are not a job offer."""
    text = normalize_post_text(text or "")
    if not text:
        raise ValueError(
            "Collez un post LinkedIn (texte de l’offre) ou indiquez une URL."
        )

    residual = _strip_urls(text)
    residual_len = len(residual)

    if pasted_only and _is_mostly_url(text, residual):
        raise ValueError(_URL_ONLY_PASTE_MSG)

    if residual_len < 50:
        raise ValueError(_URL_ONLY_PASTE_MSG if pasted_only and residual_len < 40 else _WEAK_PASTE_MSG)

    if not _looks_like_job_offer(residual):
        raise ValueError(_WEAK_PASTE_MSG)


def _strip_urls(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", " ", text, flags=re.I)
    cleaned = re.sub(r"\bwww\.\S+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\blnkd\.in/\S+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\S*linkedin\.com\S*", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_cta_noise(text: str) -> str:
    """Remove LinkedIn call-to-action fluff to judge remaining offer substance."""
    cleaned = _CTA_ONLY_RE.sub(" ", text)
    cleaned = re.sub(
        r"(?i)\b(?:partagez|share|like|comment)\b[\w\s'’-]{0,40}",
        " ",
        cleaned,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" .,:;-–!?|")


def _is_mostly_url(text: str, residual: str | None = None) -> bool:
    residual = _strip_urls(text) if residual is None else residual
    if not text.strip():
        return False
    if len(residual) <= 12:
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) == 1 and re.search(r"(?i)https?://|linkedin\.com|lnkd\.in", lines[0]):
        return len(residual) < 40
    return False


def _has_role_marker(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _ROLE_MARKERS)


def _has_hard_job_words(text: str) -> bool:
    low = (text or "").lower()
    if any(word in low for word in _HARD_JOB_WORDS):
        return True
    return bool(re.search(r"(?i)\b(?:poste|offre|hiring)\s*[:\-–]", text))


def _looks_like_job_offer(text: str) -> bool:
    """True only if text has real offer substance (role / hiring / missions), not CTA fluff."""
    core = _strip_cta_noise(text)
    if len(core) < 40:
        return False

    has_role = _has_role_marker(core)
    has_hard = _has_hard_job_words(core)

    # Role title mentioned → enough if some residual length
    if has_role and len(core) >= 40:
        return True

    # Hiring / poste / missions language with enough body
    if has_hard and len(core) >= 80:
        return True

    # Long posts with ≥2 hard signals (e.g. mission + profil) even without classic role word
    hard_hits = sum(1 for w in _HARD_JOB_WORDS if w in core.lower())
    if hard_hits >= 2 and len(core) >= 120:
        return True

    return False


def normalize_post_text(raw: str) -> str:
    """Flatten fancy LinkedIn unicode, collapse noise, keep readable French/English."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = html.unescape(text)
    # Drop decorative emoji / symbol runs used as bullets
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]+",
        " ",
        text,
    )
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_linkedin_post_text(url: str) -> str:
    """Best-effort extract of public LinkedIn post / job text from a URL."""
    cleaned = _normalize_linkedin_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        response = requests.get(cleaned, headers=headers, timeout=12, allow_redirects=True)
    except requests.RequestException as exc:
        raise ValueError(f"Impossible d’ouvrir le lien LinkedIn: {exc}") from exc

    if response.status_code >= 400:
        raise ValueError(
            "LinkedIn a refusé l’accès à ce lien. Collez plutôt le texte du post."
        )

    page = response.text or ""
    chunks: list[str] = []
    for prop in (
        "og:description",
        "twitter:description",
        "description",
        "og:title",
        "twitter:title",
    ):
        value = _meta_content(page, prop)
        if value and value not in chunks:
            chunks.append(value)

    title = _html_title(page)
    if title and title not in chunks:
        chunks.append(title)

    text = "\n\n".join(chunks).strip()
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    low = text.lower()
    if not text or "sign in" in low or ("se connecter" in low and len(text) < 80):
        return ""
    return text[:4000]


def parse_linkedin_post(raw: str, source_url: str = "") -> dict[str, Any]:
    """Turn a pasted LinkedIn post into a simple job-like dict."""
    text = normalize_post_text(raw)
    if not text:
        raise ValueError("Collez un post LinkedIn (texte de l’offre) ou indiquez une URL.")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = clean_job_title(_guess_title(lines, text))
    company = clean_company_name(_guess_company(lines, text))
    city = _guess_city(text)
    recruiter = _guess_recruiter(lines, text)

    return {
        "title": title,
        "company": company or "entreprise",
        "city": city,
        "location": city,
        "description": text[:4000],
        "url": source_url or "",
        "source": "linkedin",
        "recruiter": recruiter,
        "wants_dm": _wants_private_message(text),
    }


def clean_job_title(raw: str) -> str:
    """Short practical job title suitable for email subjects."""
    title = normalize_post_text(raw or "")
    title = re.sub(r"#\w+", " ", title)
    title = re.sub(r"(?i)\b(on linkedin|linkedin|post)\b", " ", title)
    title = re.sub(r"[|•·]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" .,:;-–!?|")
    # Drop leading marketing fluff if still present
    title = re.sub(
        r"(?i)^(nous\s+)?(recrutons|recrute|recherche|hiring)\s+(un[e]?\s+|des\s+)?",
        "",
        title,
    ).strip(" .,:;-–!?")
    # Cut if it looks like the whole post sneaked in
    if len(title) > 80:
        cut = re.split(r"[.!?\n]", title, maxsplit=1)[0].strip()
        title = cut[:80] if cut else title[:80]
    # Reject hashtag-only / noise titles
    if not title or title.count("#") > 0 or _is_noisy_title(title):
        return "Poste IT"
    return title[:80]


def clean_company_name(raw: str) -> str:
    company = normalize_post_text(raw or "")
    company = re.sub(r"#\w+", " ", company)
    company = re.sub(r"\s+", " ", company).strip(" .,:;-–!?|")
    if not company or _is_noisy_title(company) or len(company) > 60:
        return ""
    return company[:60]


def analyze_post_vs_cv(
    post_text: str = "",
    profile: dict[str, Any] | None = None,
    url: str = "",
) -> dict[str, Any]:
    """Score a LinkedIn post (paste and/or URL) against the enriched profile/CV."""
    if profile is None:
        raise ValueError("Profil CV manquant.")

    text, source_url = resolve_post_input(post=post_text, url=url)
    job = parse_linkedin_post(text, source_url=source_url)
    # Guard: parsed “job” that is only CTA / fallback title is not a real offer
    if _is_insufficient_parsed_job(job, text):
        raise ValueError(_WEAK_PASTE_MSG)
    ranked = score_jobs([job], profile, region="all", min_match=0.0)
    if ranked:
        scored = ranked[0]
    else:
        scored = {
            **job,
            "score": 15.0,
            "match_percent": 15.0,
            "match_reasons": ["Profil peu aligné avec ce post (hors domaine ou critères exclus)."],
        }

    match = float(scored.get("match_percent") or scored.get("score") or 0)
    reasons = list(scored.get("match_reasons") or [])
    if not reasons:
        reasons = ["Correspondance estimée à partir des compétences et intitulés du CV."]

    # Always keep cleaned label for UI + generation (score_jobs may keep original title)
    title = job["title"]
    company = job["company"]

    return {
        "ok": True,
        "resolved_text": text,
        "source_url": source_url,
        "job": {
            "title": title,
            "company": company,
            "city": job.get("city") or "",
            "location": job.get("location") or "",
            "description": job["description"],
            "url": source_url,
            "source": "linkedin",
            "recruiter": job.get("recruiter") or "",
            "wants_dm": job.get("wants_dm", False),
        },
        "match_percent": round(match, 1),
        "match_reasons": reasons,
        "hint": (
            "Ce post invite souvent à un message privé LinkedIn."
            if job.get("wants_dm")
            else "Vous pouvez générer un e-mail de candidature ou un message privé."
        ),
    }


def _normalize_linkedin_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL LinkedIn manquante.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in _LINKEDIN_HOSTS and not host.endswith(".linkedin.com"):
        raise ValueError("L’URL doit être un lien LinkedIn (linkedin.com ou lnkd.in).")
    return raw


def _meta_content(page: str, prop: str) -> str:
    patterns = (
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
        rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
    )
    for pat in patterns:
        m = re.search(pat, page, flags=re.I | re.S)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _html_title(page: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.I | re.S)
    if not m:
        return ""
    return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()


def _guess_title(lines: list[str], text: str) -> str:
    patterns = (
        r"(?i)(?:poste|offre)\s*[:\-–]\s*([^\n.!?]{3,90})",
        r"(?i)(?:we are hiring|hiring for)\s*[:\-–]?\s*([^\n.!?]{3,90})",
        r"(?i)(?:nous\s+)?(?:recrutons|recrute|recherche)\s+(?:un[e]?\s+|des\s+)?(.+?)(?:\s+à\s+[A-ZÀ-Ö]|!\s|\.\s|,|\n|$)",
        r"(?i)looking for\s+(?:an?\s+)?(.+?)(?:\s+in\s+|\s+at\s+|!\s|\.\s|\n|$)",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            candidate = clean_job_title(m.group(1))
            if candidate and candidate != "Poste IT" and not _is_noisy_title(candidate):
                return candidate

    for line in lines[:10]:
        low = line.lower()
        if line.startswith("#"):
            continue
        if any(k in low for k in _ROLE_MARKERS):
            # Prefer "IT Support Specialist" style phrase from the line
            m = re.search(
                r"(?i)((?:IT\s+)?(?:Support|Help\s*Desk|Network|Systems?)\s+"
                r"(?:Specialist|Technician|Engineer|Administrator)|"
                r"(?:administrateur|développeur|developpeur|ingénieur|ingenieur|"
                r"technicien|consultant|spécialiste|specialist)"
                r"[\w\s\-'/]{0,50})",
                line,
            )
            if m:
                return clean_job_title(m.group(1))
            cleaned = clean_job_title(line)
            if cleaned and cleaned != "Poste IT":
                return cleaned

    # Last resort: first non-hashtag / non-CTA content line, cleaned
    for line in lines:
        if line.startswith("#") or _is_noisy_title(line) or _CTA_ONLY_RE.search(line):
            continue
        cleaned = clean_job_title(line)
        if cleaned and cleaned != "Poste IT" and len(cleaned) <= 80:
            return cleaned
    return "Poste IT"


def _guess_company(lines: list[str], text: str) -> str:
    patterns = (
        r"(?i)rejoignez\s+([A-ZÀ-ÖØ-Ý][\w&.\-’']{1,40})",
        r"(?i)(?:chez|au sein de|at)\s+([A-ZÀ-ÖØ-Ý][\w&.\-’' ]{1,40})",
        r"(?i)(?:entreprise|company|société)\s*[:\-–]\s*([^\n.!?]{2,40})",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            company = clean_company_name(m.group(1))
            if company:
                return company

    # Hashtag brand often appears first: #Cnexia
    tags = re.findall(r"#([A-Za-z][\w]{1,30})", text)
    skip = {
        "hiring",
        "itjobs",
        "techjobs",
        "jobs",
        "moroccojobs",
        "informationtechnology",
        "helpdesk",
        "careeropportunity",
        "itsupport",
        "rabat",
        "casablanca",
        "morocco",
        "maroc",
    }
    for tag in tags:
        if tag.lower() in skip:
            continue
        # Prefer brand-looking tags (mixed case or short company names)
        if tag.lower() not in {"it", "hr", "rh"}:
            return clean_company_name(tag)
    return ""


def _guess_city(text: str) -> str:
    cities = (
        "Rabat",
        "Casablanca",
        "Marrakech",
        "Fès",
        "Fes",
        "Tanger",
        "Agadir",
        "Mohammedia",
        "Kenitra",
        "Kénitra",
        "Oujda",
        "Meknès",
        "Meknes",
        "Tétouan",
        "Tetouan",
    )
    low = text.lower()
    for city in cities:
        if city.lower() in low:
            return city
    m = re.search(r"(?i)\bà\s+([A-ZÀ-ÖØ-Ý][\w\-']{2,30})", text)
    if m:
        return m.group(1)
    return ""


def _guess_recruiter(lines: list[str], text: str) -> str:
    for line in lines[:3]:
        if len(line) < 60 and not any(c in line.lower() for c in ("http", "www.", "#")):
            if re.match(r"^[A-ZÀ-ÖØ-Ý][\w\-’']+(?:\s+[A-ZÀ-ÖØ-Ý][\w\-’']+){0,3}$", line):
                return line
    return ""


def _is_noisy_title(value: str) -> bool:
    low = (value or "").lower().strip()
    if not low:
        return True
    if low.startswith("#") or "#" in low:
        return True
    hashtag_words = len(re.findall(r"#?\b(?:hiring|jobs?|opportunity|career|morocco)\b", low))
    if hashtag_words >= 2 and len(low) > 40:
        return True
    if low in {"i", "post", "linkedin", "on linkedin"}:
        return True
    if _CTA_ONLY_RE.search(low):
        return True
    if re.search(
        r"(?i)^(contactez|envoyez|partagez|messagez|dm\b|like\b|share\b)",
        low,
    ):
        return True
    return False


def _is_insufficient_parsed_job(job: dict[str, Any], raw_text: str) -> bool:
    """Reject analyses where we only guessed fluff (e.g. CTA used as title)."""
    title = (job.get("title") or "").strip()
    company = (job.get("company") or "").strip().lower()
    if _is_noisy_title(title) or title.lower() in {"poste it", "poste", "offre"}:
        # Fallback title without company / role elsewhere → not a usable offer
        if company in {"", "entreprise", "linkedin"} and not _looks_like_job_offer(raw_text):
            return True
        if not _has_role_marker(raw_text) and not _has_hard_job_words(_strip_cta_noise(raw_text)):
            return True
    return False


def _wants_private_message(text: str) -> bool:
    blob = text.lower()
    markers = (
        "message privé",
        "message prive",
        "en mp",
        "en dm",
        "dm me",
        "envoyez-moi un message",
        "envoyez moi un message",
        "messagez-moi",
        "messagez moi",
        "contactez moi directement",
        "contactez-moi directement",
        "contactez moi",
        "contactez-moi",
        "inbox",
        "prive",
        "privé",
        "linkedin message",
    )
    return any(m in blob for m in markers)
