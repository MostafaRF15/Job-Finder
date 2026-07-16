"""Score jobs against the CV/profile with strict domain relevance + match %."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from job_agent.resume import DOMAIN_KEYWORDS
from job_agent.search import REGION_PRESETS

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "cv-match",
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


# #endregion

# Minimum CV match percentage to keep a job in results
MIN_MATCH_PERCENT = 35.0


def score_jobs(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    region: str | None = None,
    diversify: bool = False,
    min_match: float = MIN_MATCH_PERCENT,
) -> list[dict[str, Any]]:
    region_key = (region or profile.get("region") or "morocco").lower()
    preset = REGION_PRESETS.get(region_key) or REGION_PRESETS["morocco"]
    geo_terms = [t.lower() for t in preset.get("location_terms", [])]
    tier_order = bool(preset.get("tier_order"))
    cv_domain = (profile.get("cv_domain") or _infer_domain_from_profile(profile)).lower()

    scored: list[dict[str, Any]] = []
    rejected = 0
    for job in jobs:
        if _is_excluded(job, profile):
            rejected += 1
            continue
        if _is_off_domain(job, cv_domain):
            rejected += 1
            # #region agent log
            _dbg(
                "H3",
                "scoring.py:score_jobs",
                "rejected off-domain",
                {"title": (job.get("title") or "")[:70], "cv_domain": cv_domain, "source": job.get("source")},
            )
            # #endregion
            continue

        result = _score_one(job, profile, geo_terms=geo_terms, region_label=preset.get("label", region_key))
        if result["score"] < min_match:
            rejected += 1
            # #region agent log
            _dbg(
                "H3",
                "scoring.py:score_jobs",
                "rejected low match",
                {
                    "title": (job.get("title") or "")[:70],
                    "score": result["score"],
                    "min_match": min_match,
                },
            )
            # #endregion
            continue
        scored.append(result)

    # Primary sort: CV match %, then freshness
    if tier_order:
        scored.sort(
            key=lambda item: (
                item.get("tier_rank", 9),
                -item.get("score", 0),
                -(item.get("sort_ts") or 0),
            )
        )
    else:
        scored.sort(key=lambda item: (-item.get("score", 0), -(item.get("sort_ts") or 0)))
        if region_key == "morocco" or diversify:
            scored = _diversify_sources(scored)

    # #region agent log
    _dbg(
        "H2",
        "scoring.py:score_jobs",
        "scoring done",
        {
            "input": len(jobs),
            "kept": len(scored),
            "rejected": rejected,
            "cv_domain": cv_domain,
            "min_match": min_match,
            "top": [
                {"title": (j.get("title") or "")[:50], "score": j.get("score"), "source": j.get("source")}
                for j in scored[:5]
            ],
        },
    )
    # #endregion
    return scored


def _infer_domain_from_profile(profile: dict[str, Any]) -> str:
    blob = " ".join(
        list(profile.get("titles") or [])
        + list(profile.get("skills") or [])
        + list(profile.get("preferred_keywords") or [])
    ).lower()
    scores = {name: sum(1 for kw in kws if kw in blob) for name, kws in DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "it_admin"


def _is_off_domain(job: dict[str, Any], cv_domain: str) -> bool:
    """Reject jobs clearly outside the CV domain."""
    title = (job.get("title") or "").lower()
    blob = f"{title} {(job.get('description') or '')[:400]}".lower()

    job_scores = {
        name: sum(1 for kw in kws if kw in title) * 3 + sum(1 for kw in kws if kw in blob)
        for name, kws in DOMAIN_KEYWORDS.items()
    }
    job_domain = max(job_scores, key=job_scores.get)

    # IT Administrator CV must not get pure development roles
    if cv_domain == "it_admin":
        dev_markers = (
            "développeur", "developpeur", "développeuse", "developpeuse",
            "developer", "backend", "frontend",
            "fullstack", "full stack", "software engineer", "react", "django",
            "spring boot", "mobile developer",
        )
        admin_markers = (
            "administrateur", "administrator", "système", "systeme", "réseau", "reseau",
            "infrastructure", "support", "technicien", "helpdesk", "windows server",
            "active directory", "sysadmin", "exploitation",
        )
        if any(m in title for m in dev_markers) and not any(m in title for m in admin_markers):
            return True
        if job_scores.get("software", 0) >= 3 and job_scores.get("it_admin", 0) == 0:
            return True
        return False

    soft_sw = _looks_like_software_role(title)

    if job_scores[job_domain] <= 0:
        if cv_domain == "software":
            # Keep obvious software titles even when keyword lexicon misses accents/gender
            return not soft_sw and not any(kw in title for kw in DOMAIN_KEYWORDS["software"])
        return False

    if cv_domain == "software":
        # Never drop a clear software title (e.g. "Développeuse web")
        if soft_sw or job_scores.get("software", 0) > 0:
            return False
        if job_domain not in {"software"} and job_scores[job_domain] >= 2:
            return True
        return False

    if cv_domain != job_domain and job_scores[job_domain] >= 2 and job_scores.get(cv_domain, 0) == 0:
        return True
    return False


def _looks_like_software_role(title: str) -> bool:
    t = title.lower()
    stems = (
        "développ", "develop", "software", "backend", "frontend", "fullstack",
        "full stack", "full-stack", "devops", "programmer", "programmeur",
        "ingénieur logiciel", "ingenieur logiciel", "web developer", "data engineer",
        "data scientist", "mobile", "react", "django", "spring", "rails",
    )
    return any(s in t for s in stems)

def _diversify_sources(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(jobs) < 4:
        return jobs
    source_set = {job.get("source") or "unknown" for job in jobs}
    if len(source_set) < 2:
        return jobs

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    early_cap = 4
    for job in jobs:
        src = job.get("source") or "unknown"
        if counts.get(src, 0) >= early_cap:
            deferred.append(job)
            continue
        counts[src] = counts.get(src, 0) + 1
        selected.append(job)
    return selected + deferred


def _is_excluded(job: dict[str, Any], profile: dict[str, Any]) -> bool:
    blob = _job_blob(job).lower()
    for keyword in profile.get("exclude_keywords", []):
        if keyword and keyword.lower() in blob:
            return True
    return False


def _score_one(
    job: dict[str, Any],
    profile: dict[str, Any],
    geo_terms: list[str],
    region_label: str,
) -> dict[str, Any]:
    blob = _job_blob(job).lower()
    title_text = (job.get("title") or "").lower()
    reasons: list[str] = []

    titles = [t.lower() for t in profile.get("titles", [])]
    title_score = _title_similarity(titles, title_text)
    if title_score >= 0.6:
        reasons.append(f"Titre proche du CV ({int(title_score * 100)}%)")
    elif title_score >= 0.3:
        reasons.append("Titre partiellement lié au CV")

    skills = [s.lower() for s in profile.get("skills", [])]
    # Focus on the strongest CV skills so one clear hit is not diluted by a long skill list
    core_skills = skills[:8] or skills
    skill_hits = [s for s in core_skills if s in blob]
    # Also count skills present only in the job title (common on short aggregator cards)
    skill_score = min(1.0, len(skill_hits) / 3.0) if core_skills else 0.0
    if skill_hits:
        reasons.append(f"Skills CV: {', '.join(skill_hits[:6])}")

    preferred = [p.lower() for p in profile.get("preferred_keywords", [])]
    pref_hits = [p for p in preferred if p in blob]
    pref_score = len(pref_hits) / max(len(preferred), 1) if preferred else 0.0

    location_score, location_reason = _geo_score(job, profile, geo_terms, region_label)
    if location_reason:
        reasons.append(location_reason)

    # When CV has few/no lexicon skills, still credit a clear role-domain match
    domain = (profile.get("cv_domain") or "").lower()
    domain_fit = 0.0
    if domain == "software" and _looks_like_software_role(title_text):
        domain_fit = 0.45
        if not skill_hits:
            reasons.append("Même domaine que le CV (développement)")
    elif domain == "it_admin" and any(
        t in title_text
        for t in ("administrateur", "administrator", "technicien", "sysadmin", "infrastructure", "helpdesk")
    ):
        domain_fit = 0.35

    # CV-first weights: title + skills dominate (sellable match %)
    if domain_fit and skill_score < 0.35:
        skill_score = max(skill_score, domain_fit)

    score = (
        0.45 * title_score
        + 0.35 * skill_score
        + 0.10 * pref_score
        + 0.10 * location_score
    ) * 100

    enriched = dict(job)
    enriched["score"] = round(score, 1)
    enriched["match_percent"] = round(score, 1)
    enriched["match_reasons"] = reasons or ["Faible similarité avec le CV"]
    enriched["skill_hits"] = skill_hits
    enriched["title_score"] = round(title_score * 100, 1)
    enriched["location_score"] = round(location_score * 100, 1)
    return enriched


def _title_similarity(cv_titles: list[str], job_title: str) -> float:
    if not cv_titles:
        return 0.0
    best = 0.0
    job_l = job_title.lower()
    job_tokens = set(re.findall(r"[a-z0-9àâäéèêëïîôùûüç\+]+", job_l))
    job_tokens = {t for t in job_tokens if len(t) > 2}
    cv_blob = " ".join(cv_titles).lower()

    admin_job = any(
        token in job_l
        for token in (
            "administrateur", "administrator", "système", "systeme", "réseau", "reseau",
            "infrastructure", "support", "technicien", "helpdesk", "sysadmin", "exploitation",
        )
    )
    admin_cv = any(
        token in cv_blob
        for token in (
            "administrateur", "administrator", "système", "systeme", "réseau", "reseau",
            "support", "technicien", "sysadmin", "infrastructure",
        )
    )
    if admin_job and admin_cv:
        best = max(best, 0.7)

    it_job = _looks_like_software_role(job_l)
    it_cv = any(
        token in cv_blob
        for token in (
            "developer", "developpeur", "développeur", "développeuse", "developpeuse",
            "software", "backend", "frontend", "fullstack", "full stack", "ingénieur logiciel",
        )
    )
    if it_job and it_cv:
        best = max(best, 0.65)

    for cv_title in cv_titles:
        cv = cv_title.lower()
        if cv in job_l or job_l in cv:
            best = max(best, 1.0)
            continue
        cv_tokens = set(re.findall(r"[a-z0-9àâäéèêëïîôùûüç\+]+", cv))
        cv_tokens = {t for t in cv_tokens if len(t) > 2}
        if not cv_tokens:
            continue
        overlap = cv_tokens & job_tokens
        role_boost = 0.0
        for token in (
            "administrateur", "administrator", "système", "systeme", "réseau", "reseau",
            "backend", "frontend", "python", "support", "technicien", "infrastructure",
            "developer", "ingénieur", "engineer", "software",
        ):
            if token in cv and token in job_l:
                role_boost = 0.4
                break
        ratio = len(overlap) / max(len(cv_tokens), 1)
        best = max(best, min(1.0, ratio + role_boost))
    return best

def _geo_score(
    job: dict[str, Any],
    profile: dict[str, Any],
    geo_terms: list[str],
    region_label: str,
) -> tuple[float, str]:
    job_location = (job.get("location") or job.get("city") or "").lower()
    tags = " ".join(job.get("tags") or []).lower()
    blob = f"{job_location} {tags}"
    is_remote = bool(job.get("remote")) or any(
        token in job_location for token in ("remote", "worldwide", "anywhere", "global")
    )
    profile_locations = [loc.lower() for loc in profile.get("locations", [])]
    profile_hit = any(loc and loc in blob for loc in profile_locations)
    region_hit = any(term in blob for term in geo_terms)

    if profile_hit or any(c in blob for c in ("casablanca", "rabat", "maroc", "morocco")):
        return 1.0, f"Localisation OK: {job.get('city') or job.get('location') or 'N/A'}"
    if region_hit and is_remote:
        return 0.9, "Remote compatible"
    if is_remote:
        return 0.7, "Remote"
    if region_hit:
        return 0.65, f"Région: {job.get('location') or 'N/A'}"
    return 0.25, f"Localisation faible: {job.get('location') or 'N/A'}"


def _job_blob(job: dict[str, Any]) -> str:
    parts = [
        job.get("title") or "",
        job.get("company") or "",
        job.get("location") or "",
        job.get("city") or "",
        job.get("description") or "",
        " ".join(job.get("tags") or []),
        job.get("category") or "",
    ]
    text = " ".join(parts)
    return re.sub(r"<[^>]+>", " ", text)


# --- Keyword-first search helpers -------------------------------------------------

_KEYWORD_EXPAND = {
    "dev": "developpeur",
    "devs": "developpeur",
    "developer": "developpeur",
    "developers": "developpeur",
    "software": "software engineer",
    "admin": "administrateur systeme",
    "sysadmin": "administrateur systeme",
    "it": "informatique",
    "backend": "developpeur backend",
    "frontend": "developpeur frontend",
    "fullstack": "developpeur full stack",
    "full-stack": "developpeur full stack",
    "data": "data engineer",
    "devops": "ingenieur devops",
}


def expand_search_query(query: str) -> str:
    """Turn short aliases into board-friendly search phrases."""
    q = (query or "").strip()
    if not q:
        return q
    low = q.lower()
    if low in _KEYWORD_EXPAND:
        return _KEYWORD_EXPAND[low]
    return q


def keyword_terms(query: str) -> list[str]:
    """Tokens / stems used to judge if a job matches the user keywords."""
    expanded = expand_search_query(query).lower()
    raw = (query or "").strip().lower()
    terms: list[str] = []
    for chunk in (raw, expanded):
        for tok in re.findall(r"[a-z0-9àâäéèêëïîôùûüç\+]{2,}", chunk):
            if tok not in terms:
                terms.append(tok)
    # Stem-like extras for developer searches
    joined = " ".join(terms)
    if any(t in joined for t in ("dev", "develop", "développ", "software", "engineer")):
        for extra in (
            "developpeur", "développeur", "développeuse", "developer",
            "software", "backend", "frontend", "fullstack", "full stack",
            "ingénieur logiciel", "ingenieur logiciel", "programmeur",
        ):
            if extra not in terms:
                terms.append(extra)
    if any(t in joined for t in ("admin", "syst", "sysadmin", "réseau", "reseau")):
        for extra in ("administrateur", "administrator", "systeme", "système", "support", "technicien"):
            if extra not in terms:
                terms.append(extra)
    return terms


def profile_from_keywords(query: str, region: str = "morocco") -> dict[str, Any]:
    """Synthetic profile for keyword-only mode (ignores static profile.json métier)."""
    expanded = expand_search_query(query)
    terms = keyword_terms(query)
    low = expanded.lower()
    if any(k in low for k in ("develop", "développ", "software", "backend", "frontend", "devops", "data")):
        domain = "software"
        titles = ["Développeur", "Software Engineer", expanded]
        excludes = ["vendeur", "commercial", "chargé de recrutement", "call center", "femme de ménage"]
    elif any(k in low for k in ("admin", "syst", "réseau", "reseau", "support", "technicien")):
        domain = "it_admin"
        titles = ["Administrateur IT", "Administrateur Système", expanded]
        excludes = ["vendeur", "commercial", "chargé de recrutement"]
    else:
        domain = "software" if "dev" in low else "it_admin"
        titles = [expanded or query]
        excludes = ["vendeur", "commercial", "chargé de recrutement", "femme de ménage"]

    return {
        "name": "",
        "titles": titles[:6],
        "skills": [t for t in terms if len(t) > 2][:12],
        "preferred_keywords": terms[:12],
        "exclude_keywords": excludes,
        "cv_domain": domain,
        "region": region,
        "locations": ["Remote", "Morocco", "Europe", "France"],
        "category": "software-dev",
        "search_mode": "keywords_only",
    }


def _keyword_relevance(job: dict[str, Any], terms: list[str]) -> tuple[float, list[str]]:
    title = (job.get("title") or "").lower()
    blob = _job_blob(job).lower()
    title_hits = [t for t in terms if t in title]
    blob_hits = [t for t in terms if t in blob]
    reasons: list[str] = []
    if title_hits:
        reasons.append(f"Mots-clés dans le titre: {', '.join(title_hits[:4])}")
    elif blob_hits:
        reasons.append(f"Mots-clés liés: {', '.join(blob_hits[:4])}")
    # Title hits weigh more
    score = 0.0
    if title_hits:
        score = min(1.0, 0.55 + 0.15 * len(title_hits))
    elif blob_hits:
        score = min(0.75, 0.35 + 0.1 * len(blob_hits))
    return score, reasons


def score_jobs_with_keywords(
    jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    keyword_query: str,
    region: str | None = None,
    keyword_only: bool = False,
    min_match: float = MIN_MATCH_PERCENT,
) -> list[dict[str, Any]]:
    """Score jobs with keyword priority. keyword_only ignores CV-style excludes mismatch."""
    terms = keyword_terms(keyword_query)
    region_key = (region or profile.get("region") or "morocco").lower()
    preset = REGION_PRESETS.get(region_key) or REGION_PRESETS["morocco"]
    geo_terms = [t.lower() for t in preset.get("location_terms", [])]
    tier_order = bool(preset.get("tier_order"))

    scored: list[dict[str, Any]] = []
    for job in jobs:
        kw_score, kw_reasons = _keyword_relevance(job, terms)
        if keyword_only:
            if kw_score <= 0:
                continue
            # No static admin profile: light geo only
            loc_score, loc_reason = _geo_score(job, profile, geo_terms, preset.get("label", region_key))
            score = (0.85 * kw_score + 0.15 * loc_score) * 100
            reasons = kw_reasons + ([loc_reason] if loc_reason else [])
            if score < min_match:
                continue
            item = dict(job)
            item["score"] = round(score, 1)
            item["match_percent"] = round(score, 1)
            item["match_reasons"] = reasons or ["Correspondance aux mots-clés"]
            scored.append(item)
            continue

        # Hybrid: keywords first gate (do not let CV excludes/domain kill keyword intent)
        if kw_score <= 0:
            continue
        cv_result = _score_one(job, profile, geo_terms=geo_terms, region_label=preset.get("label", region_key))
        # Keywords dominate (60%) over CV match (40%)
        score = (0.60 * kw_score + 0.40 * (cv_result["score"] / 100.0)) * 100
        if score < min_match:
            continue
        item = dict(cv_result)
        item["score"] = round(score, 1)
        item["match_percent"] = round(score, 1)
        item["match_reasons"] = kw_reasons + list(cv_result.get("match_reasons") or [])
        scored.append(item)

    if tier_order:
        scored.sort(
            key=lambda item: (
                item.get("tier_rank", 9),
                -item.get("score", 0),
                -(item.get("sort_ts") or 0),
            )
        )
    else:
        scored.sort(key=lambda item: (-item.get("score", 0), -(item.get("sort_ts") or 0)))
        if region_key == "morocco":
            scored = _diversify_sources(scored)

    # #region agent log
    _dbg(
        "H2",
        "scoring.py:score_jobs_with_keywords",
        "keyword scoring done",
        {
            "keyword_only": keyword_only,
            "terms": terms[:8],
            "input": len(jobs),
            "kept": len(scored),
            "top": [{"title": (j.get("title") or "")[:50], "score": j.get("score")} for j in scored[:5]],
        },
    )
    # #endregion
    return scored
