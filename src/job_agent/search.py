"""Multi-source job search with geographic targeting."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from job_agent.morocco_sources import search_morocco_jobs

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "multi-source",
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

LAST_SOURCE_REPORT: list[dict[str, Any]] = []

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTEOK_URL = "https://remoteok.com/api"
REKRUTE_SEARCH_URL = "https://www.rekrute.com/offres.html"

SOURCE_TIER = {
    "rekrute": "morocco",
    "dreamjob": "morocco",
    "jobrapido": "morocco",
    "marocannonces": "morocco",
    "avito": "morocco",
    "alwadifa": "morocco",
    "stagiaires": "morocco",
    "arbeitnow": "europe",
    "adzuna": "europe",
    "remotive": "international",
    "remoteok": "international",
}

TIER_ORDER = {"morocco": 0, "europe": 1, "international": 2}

# Strict scopes: user choice selects which boards to query
REGION_PRESETS: dict[str, dict[str, Any]] = {
    "morocco": {
        "label": "Maroc",
        "location_terms": [
            "morocco", "maroc", "casablanca", "rabat", "marrakech", "tangier",
            "tanger", "fes", "fès", "agadir", "meknes", "oujda",
        ],
        "prefer_remote": False,
        "adzuna_country": "fr",
        "sources": ["morocco_multi"],
        "strict": True,
    },
    "europe": {
        "label": "Europe",
        "location_terms": [
            "europe", "eu", "germany", "france", "netherlands", "spain", "portugal",
            "belgium", "uk", "united kingdom", "ireland", "sweden", "poland",
            "berlin", "paris", "munich", "amsterdam", "remote",
        ],
        "prefer_remote": False,
        "adzuna_country": "fr",
        "sources": ["arbeitnow", "adzuna"],
        "strict": True,
    },
    "international": {
        "label": "International",
        "location_terms": [
            "remote", "worldwide", "anywhere", "global", "europe", "france",
            "germany", "uk", "united kingdom", "paris", "berlin",
        ],
        "prefer_remote": True,
        "adzuna_country": "gb",
        "sources": ["arbeitnow", "adzuna", "remotive", "remoteok"],
        "strict": True,
    },
    "all": {
        "label": "Tout",
        "location_terms": [
            "morocco", "maroc", "casablanca", "rabat", "europe", "france",
            "germany", "remote", "worldwide",
        ],
        "prefer_remote": True,
        "adzuna_country": "fr",
        "sources": ["morocco_multi", "arbeitnow", "adzuna", "remotive", "remoteok"],
        "strict": False,
        "tier_order": True,
    },
}


def search_jobs(
    query: str = "",
    category: str | None = "software-dev",
    limit: int = 80,
    timeout: int = 25,
    region: str = "morocco",
    sources: list[str] | None = None,
    max_age_days: int | float = 7,
) -> list[dict[str, Any]]:
    """Fetch jobs from several boards, normalize, dedupe, geo-filter lightly."""
    preset = REGION_PRESETS.get(region) or REGION_PRESETS["morocco"]
    enabled = sources or list(preset["sources"])
    LAST_SOURCE_REPORT.clear()
    # #region agent log
    _dbg(
        "H1",
        "search.py:search_jobs",
        "multi-source start",
        {
            "query": query,
            "region": region,
            "sources": enabled,
            "limit": limit,
            "max_age_days": max_age_days,
        },
    )
    # #endregion

    collected: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    # Morocco multi-source agent (primary catalog)
    if "morocco_multi" in enabled:
        try:
            morocco_jobs, report = search_morocco_jobs(
                query=query,
                timeout=min(timeout, 20),
                max_age_days=max_age_days,
            )
            collected.extend(morocco_jobs)
            LAST_SOURCE_REPORT.extend(report)
            # #region agent log
            _dbg(
                "H1",
                "search.py:search_jobs",
                "source ok",
                {"source": "morocco_multi", "count": len(morocco_jobs)},
            )
            # #endregion
        except Exception as exc:  # noqa: BLE001
            errors["morocco_multi"] = str(exc)
            # #region agent log
            _dbg("H1", "search.py:search_jobs", "source failed", {"source": "morocco_multi", "error": str(exc)})
            # #endregion

    tasks = {
        "remotive": lambda: _search_remotive(query, category, timeout),
        "arbeitnow": lambda: _search_arbeitnow(query, timeout),
        "remoteok": lambda: _search_remoteok(query, timeout),
        "adzuna": lambda: _search_adzuna(query, preset.get("adzuna_country", "fr"), timeout),
    }

    # Skip legacy single rekrute task — handled by morocco_multi
    run_sources = [name for name in enabled if name in tasks]

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(tasks[name]): name for name in run_sources}
        for future in as_completed(futures):
            name = futures[future]
            try:
                jobs = future.result()
                collected.extend(jobs)
                # #region agent log
                _dbg("H1", "search.py:search_jobs", "source ok", {"source": name, "count": len(jobs)})
                # #endregion
            except Exception as exc:  # noqa: BLE001
                errors[name] = str(exc)
                # #region agent log
                _dbg("H1", "search.py:search_jobs", "source failed", {"source": name, "error": str(exc)})
                # #endregion

    deduped = _dedupe(collected)
    # Age filter for non-Morocco boards (Morocco already filtered upstream).
    # Soft rule: drop only when we KNOW the job is older than max_age; keep undated.
    if max_age_days is not None:
        morocco_sources = {
            "rekrute", "dreamjob", "jobrapido", "marocannonces", "avito",
            "alwadifa", "stagiaires",
        }
        ma_kept = [j for j in deduped if (j.get("source") or "") in morocco_sources]
        others = [j for j in deduped if (j.get("source") or "") not in morocco_sources]
        fresh_other = _soft_age_filter(others, float(max_age_days))
        deduped = ma_kept + fresh_other

    if preset.get("strict"):
        filtered = deduped
    else:
        geo_terms = [t.lower() for t in preset.get("location_terms", [])]
        prefer_remote = bool(preset.get("prefer_remote"))
        filtered = _soft_geo_filter(deduped, geo_terms, prefer_remote=prefer_remote)

    for job in filtered:
        src = job.get("source") or ""
        job["tier"] = job.get("tier") or SOURCE_TIER.get(src, "international")
        job["tier_rank"] = TIER_ORDER.get(job["tier"], 9)

    # #region agent log
    _dbg(
        "H2",
        "search.py:search_jobs",
        "multi-source done",
        {
            "raw": len(collected),
            "deduped": len(deduped),
            "filtered": len(filtered),
            "by_source": _count_by_source(filtered),
            "errors": errors,
            "max_age_days": max_age_days,
        },
    )
    # #endregion

    return filtered[:limit]


def _search_rekrute(query: str, timeout: int) -> list[dict[str, Any]]:
    """Fetch public Rekrute search results (Morocco job board)."""
    from html import unescape
    import re

    keyword = (query or "developpeur").strip() or "developpeur"
    # Prefer French tech keywords for Moroccan boards when query is English-only
    if keyword.lower() in {"python backend", "backend", "software engineer"}:
        keyword = "developpeur python"

    params = {"keyword": keyword, "s": "1"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    response = requests.get(REKRUTE_SEARCH_URL, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    html = response.text

    pattern = re.compile(
        r"class=['\"]titreJob['\"]\s+href=\"(/offre-emploi-[^\"]+)\"[^>]*>\s*([^<]+?)\s*</a>",
        re.I | re.S,
    )
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in pattern.finditer(html):
        path = match.group(1).split("?")[0].split("#")[0]
        if path in seen:
            continue
        seen.add(path)
        raw_title = unescape(match.group(2)).strip()
        title, location = _split_rekrute_title(raw_title)
        company = _company_from_rekrute_path(path)
        jobs.append(
            {
                "id": f"rekrute-{path}",
                "title": title,
                "company": company,
                "location": location or "Maroc",
                "url": f"https://www.rekrute.com{path}",
                "description": raw_title,
                "tags": ["maroc", "rekrute"],
                "job_type": "",
                "category": "",
                "publication_date": "",
                "salary": "",
                "remote": "remote" in raw_title.lower() or "télétravail" in raw_title.lower(),
                "source": "rekrute",
                "tier": "morocco",
            }
        )
    return jobs


def _split_rekrute_title(raw: str) -> tuple[str, str]:
    if "|" in raw:
        left, right = raw.split("|", 1)
        return left.strip(), right.strip()
    return raw.strip(), "Maroc"


def _company_from_rekrute_path(path: str) -> str:
    # Example: /offre-emploi-...-recrutement-capgemini-casablanca-184487.html
    import re

    m = re.search(r"-recrutement-([a-z0-9\-]+?)(?:-casablanca|-rabat|-marrakech|-tanger|-fes|-maroc)?-\d+\.html$", path, re.I)
    if not m:
        return "Rekrute"
    slug = m.group(1).replace("-", " ").strip()
    return slug.title() if slug else "Rekrute"


def _search_remotive(query: str, category: str | None, timeout: int) -> list[dict[str, Any]]:
    params: dict[str, str] = {}
    if category:
        params["category"] = category
    if query.strip():
        params["search"] = query.strip()
    response = requests.get(REMOTIVE_URL, params=params, timeout=timeout)
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    return [_normalize_remotive(job) for job in jobs]


def _search_arbeitnow(query: str, timeout: int) -> list[dict[str, Any]]:
    response = requests.get(ARBEITNOW_URL, timeout=timeout)
    response.raise_for_status()
    jobs = response.json().get("data", [])
    normalized = [_normalize_arbeitnow(job) for job in jobs]
    return _keyword_filter(normalized, query) if query.strip() else normalized


def _search_remoteok(query: str, timeout: int) -> list[dict[str, Any]]:
    headers = {"User-Agent": "job-finder-agent/0.1 (personal search tool)"}
    response = requests.get(REMOTEOK_URL, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    # First item is often legal/meta
    jobs = [item for item in payload if isinstance(item, dict) and item.get("id") and item.get("position")]
    normalized = [_normalize_remoteok(job) for job in jobs]
    return _keyword_filter(normalized, query) if query.strip() else normalized


def _search_adzuna(query: str, country: str, timeout: int) -> list[dict[str, Any]]:
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        # #region agent log
        _dbg("H4", "search.py:_search_adzuna", "adzuna skipped (no keys)", {"country": country})
        # #endregion
        return []

    what = quote(query.strip() or "software engineer")
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        f"?app_id={app_id}&app_key={app_key}&results_per_page=50"
        f"&what={what}&content-type=application/json"
    )
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    results = response.json().get("results", [])
    return [_normalize_adzuna(job) for job in results]


def _normalize_remotive(job: dict[str, Any]) -> dict[str, Any]:
    tags = job.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {
        "id": f"remotive-{job.get('id', '')}",
        "title": (job.get("title") or "").strip(),
        "company": (job.get("company_name") or "").strip(),
        "location": (job.get("candidate_required_location") or "Remote").strip(),
        "url": (job.get("url") or "").strip(),
        "description": (job.get("description") or "").strip(),
        "tags": [str(t).strip() for t in tags if str(t).strip()],
        "job_type": (job.get("job_type") or "").strip(),
        "category": (job.get("category") or "").strip(),
        "publication_date": (job.get("publication_date") or "").strip(),
        "salary": (job.get("salary") or "").strip(),
        "remote": True,
        "source": "remotive",
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_arbeitnow(job: dict[str, Any]) -> dict[str, Any]:
    tags = job.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    remote = bool(job.get("remote"))
    location = _as_text(job.get("location")) or ("Remote" if remote else "Europe")
    return {
        "id": f"arbeitnow-{_as_text(job.get('slug') or job.get('url'))}",
        "title": _as_text(job.get("title")),
        "company": _as_text(job.get("company_name")),
        "location": location,
        "url": _as_text(job.get("url")),
        "description": _as_text(job.get("description")),
        "tags": [_as_text(t) for t in tags if _as_text(t)],
        "job_type": ", ".join(_as_text(t) for t in (job.get("job_types") or []))
        if isinstance(job.get("job_types"), list)
        else _as_text(job.get("job_types")),
        "category": "",
        "publication_date": _as_text(job.get("created_at")),
        "salary": "",
        "remote": remote,
        "source": "arbeitnow",
    }


def _normalize_remoteok(job: dict[str, Any]) -> dict[str, Any]:
    tags = job.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    title = _as_text(job.get("position") or job.get("title"))
    # RemoteOK often attaches a huge site-wide tag cloud to every listing.
    # Keep tags only when the list is small or the tag appears in the title.
    cleaned_tags: list[str] = []
    if len(tags) <= 8:
        cleaned_tags = [_as_text(t) for t in tags if _as_text(t)]
    else:
        title_l = title.lower()
        cleaned_tags = [_as_text(t) for t in tags if _as_text(t) and _as_text(t).lower() in title_l]

    location = _as_text(job.get("location")) or "Remote"
    salary = ""
    if job.get("salary_min") or job.get("salary_max"):
        salary = f"{job.get('salary_min', '')}-{job.get('salary_max', '')}".strip("-")
    return {
        "id": f"remoteok-{_as_text(job.get('id'))}",
        "title": title,
        "company": _as_text(job.get("company")),
        "location": location,
        "url": _as_text(job.get("url") or job.get("apply_url")),
        "description": _as_text(job.get("description")),
        "tags": cleaned_tags,
        "job_type": "",
        "category": "",
        "publication_date": _as_text(job.get("date")),
        "salary": salary,
        "remote": True,
        "source": "remoteok",
    }


def _normalize_adzuna(job: dict[str, Any]) -> dict[str, Any]:
    loc = job.get("location") or {}
    area = loc.get("display_name") if isinstance(loc, dict) else str(loc or "")
    salary = ""
    if job.get("salary_min") or job.get("salary_max"):
        salary = f"{job.get('salary_min', '')}-{job.get('salary_max', '')}".strip("-")
    return {
        "id": f"adzuna-{job.get('id', '')}",
        "title": (job.get("title") or "").strip(),
        "company": ((job.get("company") or {}).get("display_name") if isinstance(job.get("company"), dict) else "")
        or "",
        "location": (area or "").strip(),
        "url": (job.get("redirect_url") or job.get("url") or "").strip(),
        "description": (job.get("description") or "").strip(),
        "tags": [],
        "job_type": (job.get("contract_time") or "").strip(),
        "category": ((job.get("category") or {}).get("label") if isinstance(job.get("category"), dict) else "")
        or "",
        "publication_date": (job.get("created") or "").strip(),
        "salary": salary,
        "remote": "remote" in (area or "").lower(),
        "source": "adzuna",
    }


def _soft_age_filter(jobs: list[dict[str, Any]], max_age_days: float) -> list[dict[str, Any]]:
    """Drop jobs known to be older than max_age_days; keep undated jobs."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - max_age_days * 86400
    kept: list[dict[str, Any]] = []
    for job in jobs:
        ts = float(job.get("sort_ts") or 0)
        if ts <= 0:
            pub = (job.get("publication_date") or "").strip()
            if pub:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(pub[:19], fmt).replace(tzinfo=timezone.utc)
                        ts = parsed.timestamp()
                        break
                    except ValueError:
                        continue
        if ts > 0 and ts < cutoff:
            continue
        kept.append(job)
    return kept


def _keyword_filter(jobs: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        return jobs

    matched: list[dict[str, Any]] = []
    tech_fallback: list[dict[str, Any]] = []
    for job in jobs:
        title = (job.get("title") or "").lower()
        tags = " ".join(job.get("tags") or []).lower()
        short = f"{title} {tags} {(job.get('company') or '').lower()}"
        full = f"{short} {(job.get('description') or '')[:2500].lower()}"

        if any(token in short for token in tokens):
            matched.append(job)
        elif any(token in full for token in tokens) and _looks_tech(title):
            matched.append(job)
        elif _looks_tech(title):
            tech_fallback.append(job)

    if len(matched) >= 12:
        return matched
    return matched + tech_fallback[: max(20, 40 - len(matched))]


def _looks_tech(blob: str) -> bool:
    role_markers = (
        "engineer", "developer", "software", "backend", "frontend", "devops",
        "full stack", "fullstack", "sre", "platform", "programmer",
    )
    skill_markers = (
        "python", "javascript", "typescript", "java", "golang", "rust",
        "react", "django", "flask", "kubernetes", "docker", "aws",
    )
    return any(marker in blob for marker in role_markers) or any(marker in blob for marker in skill_markers)


def _soft_geo_filter(
    jobs: list[dict[str, Any]],
    geo_terms: list[str],
    prefer_remote: bool,
) -> list[dict[str, Any]]:
    if not geo_terms:
        return jobs

    strong: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    for job in jobs:
        loc = (job.get("location") or "").lower()
        tags = " ".join(job.get("tags") or []).lower()
        blob = f"{loc} {tags}"
        is_remote = bool(job.get("remote")) or "remote" in loc or "worldwide" in loc or "anywhere" in loc
        matches = any(term in blob for term in geo_terms)
        if matches or (prefer_remote and is_remote) or is_remote:
            strong.append(job)
        else:
            weak.append(job)

    # Keep some weak matches so keyword-relevant onsite roles are not lost entirely
    return strong + weak[: max(5, len(strong) // 10)]


def _dedupe(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in jobs:
        key = (job.get("url") or "").strip().lower()
        if not key:
            key = f"{(job.get('title') or '').lower()}|{(job.get('company') or '').lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    return out


def _count_by_source(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        src = job.get("source") or "unknown"
        counts[src] = counts.get(src, 0) + 1
    return counts
