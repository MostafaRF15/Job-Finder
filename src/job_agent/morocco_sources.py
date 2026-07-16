"""Morocco-first job search across multiple recruitment websites.

Many boards block bots (Cloudflare) or have broken SSL. This module:
1. Searches every reachable public source in parallel
2. Reports which catalog sites were checked / blocked / failed
3. Returns normalized structured listings (JSON-friendly)
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, unquote

import requests

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "morocco-multi",
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

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Full trusted catalog from product requirements
MOROCCO_SITE_CATALOG: list[dict[str, str]] = [
    {"id": "rekrute", "name": "Rekrute", "url": "https://www.rekrute.com", "group": "primary"},
    {"id": "emploi_ma", "name": "Emploi.ma", "url": "https://www.emploi.ma", "group": "primary"},
    {"id": "dreamjob", "name": "Dreamjob", "url": "https://www.dreamjob.ma", "group": "primary"},
    {"id": "anapec", "name": "ANAPEC", "url": "https://www.anapec.org", "group": "primary"},
    {"id": "emploi_public", "name": "Emploi Public", "url": "https://www.emploi-public.ma", "group": "primary"},
    {"id": "alwadifa", "name": "Alwadifa Maroc", "url": "https://www.alwadifa-maroc.com", "group": "primary"},
    {"id": "bayt", "name": "Bayt Morocco", "url": "https://www.bayt.com/en/morocco/", "group": "primary"},
    {"id": "indeed_ma", "name": "Indeed Maroc", "url": "https://ma.indeed.com", "group": "primary"},
    {"id": "jooble_ma", "name": "Jooble Maroc", "url": "https://ma.jooble.org", "group": "primary"},
    {"id": "jobrapido", "name": "Jobrapido Maroc", "url": "https://ma.jobrapido.com", "group": "primary"},
    {"id": "optioncarriere", "name": "Option Carrière", "url": "https://www.optioncarriere.ma", "group": "primary"},
    {"id": "trovit", "name": "Trovit Emploi", "url": "https://emploi.trovit.ma", "group": "primary"},
    {"id": "marocannonces", "name": "MarocAnnonces", "url": "https://www.marocannonces.com", "group": "primary"},
    {"id": "avito", "name": "Avito Emploi", "url": "https://www.avito.ma/fr/maroc/emploi", "group": "primary"},
    {"id": "moncallcenter", "name": "MonCallCenter", "url": "https://www.moncallcenter.ma", "group": "primary"},
    {"id": "ifcarjob", "name": "IfCarJob", "url": "https://www.ifcarjob.com", "group": "primary"},
    {"id": "jobzyn", "name": "Jobzyn", "url": "https://www.jobzyn.com", "group": "primary"},
    {"id": "amaljob", "name": "AmalJob", "url": "https://www.amaljob.com", "group": "primary"},
    {"id": "m_job", "name": "M-Job", "url": "https://www.m-job.ma", "group": "primary"},
    {"id": "marocemploi", "name": "MarocEmploi", "url": "https://www.marocemploi.net", "group": "primary"},
    {"id": "marocforceemploi", "name": "Maroc Force Emploi", "url": "https://www.marocforceemploi.com", "group": "primary"},
    {"id": "menarajob", "name": "MenaraJob", "url": "https://www.menarajob.com", "group": "primary"},
    {"id": "tanmia", "name": "Tanmia", "url": "https://www.tanmia.ma", "group": "primary"},
    {"id": "stagiaires", "name": "Stagiaires.ma", "url": "https://www.stagiaires.ma", "group": "primary"},
    {"id": "manpower", "name": "Manpower Maroc", "url": "https://www.manpower-maroc.com", "group": "agency"},
    {"id": "adecco", "name": "Adecco Maroc", "url": "https://www.adecco-maroc.com", "group": "agency"},
    {"id": "tectra", "name": "Tectra", "url": "https://www.tectra.ma", "group": "agency"},
    {"id": "linkedin", "name": "LinkedIn Jobs", "url": "https://www.linkedin.com/jobs/", "group": "network"},
]


MAX_AGE_DAYS = 7


def search_morocco_jobs(
    query: str = "",
    timeout: int = 18,
    max_age_days: int | float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Search reachable Morocco sources. Returns (jobs, source_report)."""
    q = (query or "developpeur").strip() or "developpeur"
    age = MAX_AGE_DAYS if max_age_days is None else float(max_age_days)
    # #region agent log
    _dbg("H1", "morocco_sources.py:search_morocco_jobs", "start", {"query": q, "max_age_days": age})
    # #endregion

    parsers = {
        "rekrute": lambda: _parse_rekrute(q, timeout),
        "dreamjob": lambda: _parse_dreamjob(q, timeout),
        "jobrapido": lambda: _parse_jobrapido(q, timeout),
        "marocannonces": lambda: _parse_marocannonces(q, timeout),
        "avito": lambda: _parse_avito(q, timeout),
        "alwadifa": lambda: _parse_alwadifa(q, timeout),
        "stagiaires": lambda: _parse_stagiaires(q, timeout),
    }

    jobs: list[dict[str, Any]] = []
    report_map: dict[str, dict[str, Any]] = {
        site["id"]: {
            "id": site["id"],
            "name": site["name"],
            "url": site["url"],
            "group": site["group"],
            "status": "not_implemented",
            "jobs_found": 0,
            "note": "",
        }
        for site in MOROCCO_SITE_CATALOG
    }

    # Known blocked / unavailable from runtime probes (re-tried when registry cooldown expires)
    blocked_defaults = {
        "emploi_ma": "Blocked by Cloudflare from this server",
        "bayt": "Blocked by Cloudflare from this server",
        "indeed_ma": "HTTP 403 from this server",
        "jooble_ma": "Blocked by Cloudflare from this server",
        "anapec": "SSL/connection failure from this server",
        "m_job": "SSL failure from this server",
        "adecco": "Connection failure from this server",
        "linkedin": "Requires authenticated access; not scraped",
        "trovit": "Redirect/blocked (HTTP 405)",
        "amaljob": "Site returned empty page",
        "optioncarriere": "Captcha / verification required",
    }
    from job_agent.source_registry import should_retry, update_from_report

    for site_id, note in blocked_defaults.items():
        if site_id in report_map and not should_retry(site_id):
            report_map[site_id]["status"] = "unavailable"
            report_map[site_id]["note"] = note

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fn): name for name, fn in parsers.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                found = future.result()
                jobs.extend(found)
                report_map[name]["status"] = "ok"
                report_map[name]["jobs_found"] = len(found)
                # #region agent log
                _dbg("H1", "morocco_sources.py:parser", "source ok", {"source": name, "count": len(found)})
                # #endregion
            except Exception as exc:  # noqa: BLE001
                report_map[name]["status"] = "error"
                report_map[name]["note"] = str(exc)[:180]
                # #region agent log
                _dbg("H1", "morocco_sources.py:parser", "source failed", {"source": name, "error": str(exc)[:180]})
                # #endregion

    # Mark remaining catalog entries still "not_implemented"
    for site_id, row in report_map.items():
        if row["status"] == "not_implemented":
            row["note"] = "Listed in catalog; parser not enabled yet (or homepage-only)"

    deduped = _dedupe_jobs(jobs)
    fresh, dropped = _filter_recent(deduped, max_age_days=age)
    sorted_jobs = sorted(fresh, key=lambda j: j.get("sort_ts") or 0, reverse=True)

    report = list(report_map.values())
    try:
        update_from_report(report)
    except Exception:
        pass
    # #region agent log
    _dbg(
        "H2",
        "morocco_sources.py:search_morocco_jobs",
        "done",
        {
            "query": q,
            "raw": len(jobs),
            "deduped": len(deduped),
            "fresh": len(sorted_jobs),
            "dropped_old_or_undated": dropped,
            "by_source": _count(sorted_jobs),
            "ok_sources": [r["id"] for r in report if r["status"] == "ok"],
            "oldest_kept_days": _age_days_sample(sorted_jobs),
        },
    )
    # #endregion
    return sorted_jobs, report


def _filter_recent(jobs: list[dict[str, Any]], max_age_days: int = 7) -> tuple[list[dict[str, Any]], int]:
    """Keep only jobs with a known publication date within max_age_days."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - max_age_days * 86400
    kept: list[dict[str, Any]] = []
    dropped = 0
    for job in jobs:
        ts = float(job.get("sort_ts") or 0)
        dated = bool(job.get("date_known"))
        pub = (job.get("publication_date") or "").strip()
        # Also parse relative "il y a 40 jours" even if sort_ts was wrong
        if pub and not dated:
            rel = _parse_relative_fr(pub)
            if rel:
                ts = rel
                dated = True
        if not dated or ts <= 0:
            dropped += 1
            continue
        if ts < cutoff:
            dropped += 1
            # #region agent log
            _dbg(
                "H3",
                "morocco_sources.py:_filter_recent",
                "dropped old job",
                {
                    "title": (job.get("title") or "")[:60],
                    "source": job.get("source"),
                    "publication_date": pub,
                    "age_days": round((now - ts) / 86400, 1),
                },
            )
            # #endregion
            continue
        kept.append(job)
    return kept, dropped


def _age_days_sample(jobs: list[dict[str, Any]]) -> list[float]:
    now = datetime.now(timezone.utc).timestamp()
    ages = []
    for job in jobs[:8]:
        ts = float(job.get("sort_ts") or 0)
        if ts:
            ages.append(round((now - ts) / 86400, 1))
    return ages


def _get(url: str, timeout: int) -> str:
    response = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.text


def _job(
    *,
    title: str,
    company: str,
    city: str,
    url: str,
    source: str,
    source_website: str,
    description: str = "",
    salary: str = "",
    contract_type: str = "",
    experience: str = "",
    skills: list[str] | None = None,
    publication_date: str = "",
    sort_ts: float = 0,
) -> dict[str, Any]:
    date_known = bool(sort_ts and sort_ts > 0)
    return {
        "id": f"{source}-{abs(hash(url))}",
        "title": _clean(title),
        "company": _clean(company) or source,
        "city": _clean(city) or "Maroc",
        "location": _clean(city) or "Maroc",
        "contract_type": _clean(contract_type),
        "salary": _clean(salary),
        "experience": _clean(experience),
        "skills": skills or [],
        "description": _clean(description)[:1200],
        "url": url,
        "source": source,
        "source_website": source_website,
        "publication_date": _clean(publication_date),
        "sort_ts": float(sort_ts or 0),
        "date_known": date_known,
        "remote": bool(re.search(r"remote|télétravail|teletravail", f"{title} {description}", re.I)),
        "tags": ["maroc", source],
        "job_type": _clean(contract_type),
        "category": "",
        "tier": "morocco",
        "tier_rank": 0,
    }


def _clean(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _parse_rekrute(query: str, timeout: int) -> list[dict[str, Any]]:
    keyword = query
    if keyword.lower() in {"python backend", "backend", "software engineer"}:
        keyword = "developpeur python"
    html = _get(f"https://www.rekrute.com/offres.html?keyword={quote_plus(keyword)}&s=1", timeout)
    pattern = re.compile(
        r"class=['\"]titreJob['\"]\s+href=\"(/offre-emploi-[^\"]+)\"[^>]*>\s*([^<]+?)\s*</a>",
        re.I | re.S,
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in pattern.finditer(html):
        path = match.group(1).split("?")[0].split("#")[0]
        if path in seen:
            continue
        seen.add(path)
        raw = unescape(match.group(2)).strip()
        title, city = (raw.split("|", 1) + ["Maroc"])[:2] if "|" in raw else (raw, "Maroc")
        company = "Rekrute"
        m = re.search(
            r"-recrutement-([a-z0-9\-]+?)(?:-casablanca|-rabat|-marrakech|-tanger|-fes|-maroc)?-\d+\.html$",
            path,
            re.I,
        )
        if m:
            company = m.group(1).replace("-", " ").title()
        out.append(
            _job(
                title=title.strip(),
                company=company,
                city=city.strip(),
                url=f"https://www.rekrute.com{path}",
                source="rekrute",
                source_website="https://www.rekrute.com",
                description=raw,
                publication_date="",
            )
        )
    return out


def _parse_dreamjob(query: str, timeout: int) -> list[dict[str, Any]]:
    html = _get(f"https://www.dreamjob.ma/?s={quote_plus(query)}", timeout)
    articles = re.findall(r"<article[^>]*>(.*?)</article>", html, re.I | re.S)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for article in articles:
        m = re.search(
            r'<h3 class="jeg_post_title">\s*<a href="(https://www\.dreamjob\.ma/emploi/[^"]+)"[^>]*>(.*?)</a>',
            article,
            re.I | re.S,
        )
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        if url in seen:
            continue
        seen.add(url)
        date_m = re.search(r'jeg_meta_date">.*?</i>\s*([0-9]{2}/[0-9]{2}/[0-9]{4})', article, re.I | re.S)
        pub = date_m.group(1) if date_m else ""
        company = ""
        for brand in ("Capgemini", "Deloitte", "CGI", "Accenture", "Oracle", "Marjane", "Jumia", "BANK OF AFRICA"):
            if brand.lower() in title.lower() or brand.lower() in article.lower():
                company = brand
                break
        out.append(
            _job(
                title=title,
                company=company or "Dreamjob",
                city=_guess_city(title + " " + article[:400]),
                url=url,
                source="dreamjob",
                source_website="https://www.dreamjob.ma",
                description=title,
                publication_date=pub,
                sort_ts=_parse_fr_date(pub),
                contract_type=_guess_contract(title),
            )
        )
    return out


def _parse_jobrapido(query: str, timeout: int) -> list[dict[str, Any]]:
    html = _get(f"https://ma.jobrapido.com/?q={quote_plus(query)}&l=Maroc", timeout)
    adverts = re.findall(r"data-advert='(\{.*?\})'", html)
    out: list[dict[str, Any]] = []
    for raw in adverts:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        title = _clean(obj.get("title") or "")
        if not title:
            continue
        city = _clean((obj.get("locationsLabel") or obj.get("location") or "Maroc").replace("<br>", ", "))
        url = obj.get("openAdvertUrl") or ""
        # Prefer original employer URL when embedded
        if "redirectTo=" in url:
            try:
                redirect = unquote(unquote(url.split("redirectTo=", 1)[1].split("&", 1)[0]))
                if redirect.startswith("http"):
                    url = redirect
            except Exception:  # noqa: BLE001
                pass
        pub = obj.get("date") or ""
        out.append(
            _job(
                title=title,
                company=obj.get("company") or obj.get("companyForTitle") or "Jobrapido",
                city=city,
                url=url or f"https://ma.jobrapido.com/",
                source="jobrapido",
                source_website="https://ma.jobrapido.com",
                description=obj.get("bodyHighlighted") or title,
                salary=_clean(str(obj.get("salary") or "")),
                publication_date=str(pub),
                sort_ts=_parse_short_fr_date(str(pub)),
                skills=[t for t in (obj.get("tags") or []) if isinstance(t, str)][:12],
            )
        )
    return out


def _parse_marocannonces(query: str, timeout: int) -> list[dict[str, Any]]:
    # Keyword search path is unstable; use emploi category then filter client-side
    html = _get("https://www.marocannonces.com/categorie/309/Offres-emploi.html", timeout)
    blocks = re.findall(
        r'<article class="listing[^"]*">\s*<a[^>]+href="([^"]+)"[^>]*>.*?<h3>\s*([^<]+?)\s*</h3>',
        html,
        re.I | re.S,
    )
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    out: list[dict[str, Any]] = []
    for href, title in blocks:
        title_c = _clean(title)
        blob = title_c.lower()
        if tokens and not any(t in blob for t in tokens):
            # keep some broad emploi results if query is generic
            if not any(k in blob for k in ("develop", "python", "ingénieur", "ingenieur", "software", "data", "devops")):
                continue
        if href.startswith("http"):
            url = href
        else:
            url = "https://www.marocannonces.com/" + href.lstrip("/")
        out.append(
            _job(
                title=title_c,
                company="MarocAnnonces",
                city=_guess_city(title_c),
                url=url,
                source="marocannonces",
                source_website="https://www.marocannonces.com",
                description=title_c,
                experience=_guess_experience(title_c),
            )
        )
    return out


def _parse_avito(query: str, timeout: int) -> list[dict[str, Any]]:
    html = _get(f"https://www.avito.ma/fr/maroc/offres_d_emploi?q={quote_plus(query)}", timeout)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    ads = (
        data.get("props", {})
        .get("pageProps", {})
        .get("componentProps", {})
        .get("ads", [])
    )
    out: list[dict[str, Any]] = []
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        title = ad.get("subject") or ""
        if not title:
            continue
        seller = ad.get("seller") or {}
        company = seller.get("name") if isinstance(seller, dict) else ""
        href = ad.get("href") or ""
        if href and href.startswith("/"):
            href = "https://www.avito.ma" + href
        pub = ad.get("date") or ""
        desc = ad.get("description") or ""
        out.append(
            _job(
                title=title,
                company=company or "Avito",
                city=ad.get("location") or "Maroc",
                url=href or "https://www.avito.ma/fr/maroc/offres_d_emploi",
                source="avito",
                source_website="https://www.avito.ma",
                description=desc,
                publication_date=str(pub),
                sort_ts=_parse_relative_fr(str(pub)),
                salary=_format_avito_price(ad.get("price")),
                experience=_guess_experience(desc),
                skills=_guess_skills(f"{title} {desc}"),
                contract_type=_guess_contract(f"{title} {desc}"),
            )
        )
    return out


def _parse_alwadifa(query: str, timeout: int) -> list[dict[str, Any]]:
    """Alwadifa Maroc public listings (Arabic/FR mix)."""
    html = _get(f"https://www.alwadifa-maroc.com/?s={quote_plus(query)}", timeout)
    now = datetime.now(timezone.utc).timestamp()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'href=["\']([^"\']*?/offre/show/id/(\d+))["\']',
        html,
        re.I,
    ):
        href = m.group(1)
        job_id = m.group(2)
        if job_id in seen:
            continue
        seen.add(job_id)
        if href.startswith("/"):
            href = "https://www.alwadifa-maroc.com" + href
        start = max(0, m.start() - 180)
        end = min(len(html), m.end() + 220)
        chunk = unescape(re.sub(r"<[^>]+>", " ", html[start:end]))
        chunk = re.sub(r"\s+", " ", chunk).strip()
        title = chunk[:140] if chunk else f"Offre Alwadifa #{job_id}"
        # Skip pure nav crumbs
        if len(title) < 12:
            continue
        out.append(
            _job(
                title=title,
                company="Alwadifa Maroc",
                city="Maroc",
                url=href,
                source="alwadifa",
                source_website="https://www.alwadifa-maroc.com",
                description=chunk[:400],
                publication_date="récente",
                sort_ts=now,
            )
        )
        if len(out) >= 25:
            break
    return out


def _parse_stagiaires(query: str, timeout: int) -> list[dict[str, Any]]:
    """Stagiaires.ma search — best-effort listing links."""
    html = _get(f"https://www.stagiaires.ma/?s={quote_plus(query)}", timeout)
    now = datetime.now(timezone.utc).timestamp()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'href=["\'](https?://(?:www\.)?stagiaires\.ma/[^"\']+)["\']', html, re.I):
        href = m.group(1).split("#")[0]
        if href in seen or "wp-" in href or "/tag/" in href or "/category/" in href:
            continue
        if not re.search(r"stage|emploi|offre|job", href, re.I):
            continue
        seen.add(href)
        start = max(0, m.start() - 120)
        end = min(len(html), m.end() + 180)
        chunk = unescape(re.sub(r"<[^>]+>", " ", html[start:end]))
        chunk = re.sub(r"\s+", " ", chunk).strip()
        title = chunk[:120] if len(chunk) > 15 else href.rstrip("/").split("/")[-1].replace("-", " ")
        out.append(
            _job(
                title=title.title() if title else "Offre Stagiaires.ma",
                company="Stagiaires.ma",
                city="Maroc",
                url=href,
                source="stagiaires",
                source_website="https://www.stagiaires.ma",
                description=chunk[:400],
                publication_date="récente",
                sort_ts=now,
            )
        )
        if len(out) >= 20:
            break
    return out


def _format_avito_price(price: Any) -> str:
    if not isinstance(price, dict):
        return ""
    value = price.get("value") or price.get("formatted")
    return str(value) if value else ""


def _guess_city(text: str) -> str:
    cities = [
        "Casablanca", "Rabat", "Marrakech", "Tanger", "Tangier", "Fès", "Fes",
        "Agadir", "Meknès", "Meknes", "Oujda", "Tétouan", "Kenitra", "Kénitra",
        "Mohammedia", "El Jadida", "Nador", "Settat",
    ]
    lower = text.lower()
    for city in cities:
        if city.lower() in lower:
            return city
    return "Maroc"


def _guess_contract(text: str) -> str:
    lower = text.lower()
    if "cdi" in lower:
        return "CDI"
    if "cdd" in lower:
        return "CDD"
    if "stage" in lower or "stagiaire" in lower:
        return "Stage"
    if "freelance" in lower or "consultant" in lower:
        return "Freelance"
    return ""


def _guess_experience(text: str) -> str:
    m = re.search(r'(\d+\s*(?:ans|an|years?)\s*(?:d[e\' ]expérience|experience)?)', text, re.I)
    if m:
        return m.group(1)
    if re.search(r"junior|débutant|debutant", text, re.I):
        return "Junior"
    if re.search(r"senior|confirmé|confirme", text, re.I):
        return "Senior"
    if re.search(r"bac\s*\+?\s*\d", text, re.I):
        m2 = re.search(r"(bac\s*\+?\s*\d)", text, re.I)
        return m2.group(1) if m2 else ""
    return ""


def _guess_skills(text: str) -> list[str]:
    lexicon = [
        "python", "java", "javascript", "typescript", "react", "angular", "vue",
        "django", "flask", "spring", "sql", "postgresql", "mongodb", "docker",
        "kubernetes", "aws", "azure", "gcp", "linux", "git", "devops", "excel",
    ]
    lower = text.lower()
    return [s for s in lexicon if re.search(rf"(?<![a-z0-9]){re.escape(s)}(?![a-z0-9])", lower)]


def _parse_fr_date(value: str) -> float:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _parse_short_fr_date(value: str) -> float:
    # e.g. "07 juil."
    months = {
        "janv": 1, "févr": 2, "fevr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
        "juil": 7, "août": 8, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
    }
    m = re.search(r"(\d{1,2})\s*([a-zéû\.]+)", value.lower())
    if not m:
        return 0.0
    day = int(m.group(1))
    mon_key = m.group(2).strip(".")[:4]
    month = None
    for key, num in months.items():
        if mon_key.startswith(key[:4]) or key.startswith(mon_key):
            month = num
            break
    if not month:
        return 0.0
    year = datetime.now(timezone.utc).year
    try:
        return datetime(year, month, day, tzinfo=timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _parse_relative_fr(value: str) -> float:
    now = datetime.now(timezone.utc).timestamp()
    lower = value.lower().strip()
    if not lower:
        return 0.0
    if "il y a un jour" in lower or "il y a 1 jour" in lower:
        return now - 86400
    if "il y a une heure" in lower or "à l'instant" in lower or "just now" in lower:
        return now - 3600
    m = re.search(r"il y a\s+(\d+)\s+(heure|heures|jour|jours|minute|minutes|semaine|semaines|mois)", lower)
    if not m:
        return 0.0
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("minute"):
        return now - n * 60
    if unit.startswith("heure"):
        return now - n * 3600
    if unit.startswith("jour"):
        return now - n * 86400
    if unit.startswith("semaine"):
        return now - n * 7 * 86400
    if unit.startswith("mois"):
        return now - n * 30 * 86400
    return 0.0


def _dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer original employer URLs over aggregator mirrors when titles/companies collide."""
    priority = {
        "rekrute": 1,
        "dreamjob": 2,
        "avito": 3,
        "marocannonces": 4,
        "jobrapido": 5,
    }
    best: dict[str, dict[str, Any]] = {}
    for job in jobs:
        key = re.sub(
            r"\W+",
            "",
            f"{(job.get('title') or '').lower()}|{(job.get('company') or '').lower()}|{(job.get('city') or '').lower()}",
        )
        url = (job.get("url") or "").lower()
        if url and url not in {b.get("url", "").lower() for b in best.values()}:
            # also key by normalized title+company
            pass
        existing = best.get(key)
        if not existing:
            best[key] = job
            continue
        old_p = priority.get(existing.get("source", ""), 50)
        new_p = priority.get(job.get("source", ""), 50)
        # Prefer non-aggregator / earlier primary source; also prefer richer description
        if new_p < old_p or (
            new_p == old_p and len(job.get("description") or "") > len(existing.get("description") or "")
        ):
            best[key] = job
    return list(best.values())


def _count(jobs: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for job in jobs:
        src = job.get("source") or "?"
        out[src] = out.get(src, 0) + 1
    return out
