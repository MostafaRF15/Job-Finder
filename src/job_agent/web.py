"""Simple web UI for the Job Finder Agent."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

from job_agent.linkedin import analyze_post_vs_cv
from job_agent.llm import explain_matches
from job_agent.pdf_export import build_letter_pdf
from job_agent.profile import load_profile
from job_agent.resume import enrich_profile_from_resume, extract_text, profile_for_writing
from job_agent.scoring import (
    expand_search_query,
    profile_from_keywords,
    score_jobs,
    score_jobs_with_keywords,
)
from job_agent.morocco_sources import MAX_AGE_DAYS
from job_agent.search import LAST_SOURCE_REPORT, REGION_PRESETS, SOURCE_TIER, search_jobs
from job_agent.seen_jobs import annotate_new, mark_seen, sort_new_first
from job_agent.source_registry import load_registry
from job_agent.storage import save_results
from job_agent.writing import (
    generate_application_email,
    generate_cover_letter,
    generate_linkedin_message,
    rewrite_document,
)

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")
_SESSION_DEBUG_LOG = Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-90a300.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "web-resume",
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
            "sessionId": "90a300",
            "runId": "pdf-export",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _SESSION_DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


# #endregion

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB


@app.after_request
def _no_cache_static(response):
    # Avoid stale UI during iterative development (buttons/modal updates)
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return response


@app.get("/health")
def health():
    """Lightweight liveness check (used by monitoring / CI)."""
    return jsonify({"ok": True, "status": "healthy"})


@app.get("/")
def index():
    profile = load_profile()
    # UI zones: Maroc / International / Tout (Europe merged into International)
    ui_regions = ("morocco", "international", "all")
    regions = [
        {"id": key, "label": REGION_PRESETS[key]["label"]}
        for key in ui_regions
        if key in REGION_PRESETS
    ]
    default_region = profile.get("region", "morocco")
    if default_region not in ui_regions:
        default_region = "morocco"
    return render_template(
        "index.html",
        profile=profile,
        regions=regions,
        default_region=default_region,
    )


@app.get("/linkedin")
def linkedin_page():
    return render_template("linkedin.html")


@app.post("/api/search")
def api_search():
    query = (request.form.get("query") or "").strip()
    limit = int(request.form.get("limit") or 40)
    use_llm = False  # UI option removed
    region = (request.form.get("region") or "morocco").strip().lower()
    if region not in REGION_PRESETS:
        region = "morocco"

    try:
        max_age_days = int(request.form.get("max_age") or MAX_AGE_DAYS)
    except ValueError:
        max_age_days = MAX_AGE_DAYS
    if max_age_days not in {1, 7, 15, 30}:
        max_age_days = MAX_AGE_DAYS

    profile = load_profile()
    profile["region"] = region
    resume_meta: dict[str, Any] = {"uploaded": False}
    user_query = query  # keep typed keywords separate from CV-derived query

    upload = request.files.get("resume")
    has_resume = bool(upload and upload.filename)
    has_query = bool(user_query)
    if not has_query and not has_resume:
        return jsonify(
            {
                "ok": False,
                "error": "Ajoutez un mot-clé ou importez votre CV (ou les deux) pour simplifier la recherche.",
            }
        ), 400

    # #region agent log
    _dbg(
        "H3",
        "web.py:api_search",
        "search request",
        {
            "query": user_query,
            "limit": limit,
            "region": region,
            "has_resume": has_resume,
            "use_llm": use_llm,
            "max_age_days": max_age_days,
        },
    )
    try:
        _SESSION_DEBUG = Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-90a300.log")
        _SESSION_DEBUG.parent.mkdir(parents=True, exist_ok=True)
        with _SESSION_DEBUG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "90a300",
                        "runId": "kw-priority",
                        "hypothesisId": "H1",
                        "location": "web.py:api_search:entry",
                        "message": "search mode inputs",
                        "data": {
                            "user_query": user_query,
                            "has_resume": has_resume,
                            "has_query": has_query,
                            "profile_titles": (profile.get("titles") or [])[:3],
                            "profile_excludes": (profile.get("exclude_keywords") or [])[:6],
                            "profile_domain": profile.get("cv_domain"),
                        },
                        "timestamp": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    if has_resume:
        try:
            raw = upload.read()
            text = extract_text(upload.filename, raw)
            profile = enrich_profile_from_resume(profile, text)
            resume_meta = {
                "uploaded": True,
                "filename": upload.filename,
                "name": profile.get("name"),
                "skills_found": profile.get("resume_skills_found", []),
                "titles_found": profile.get("resume_titles_found", []),
                "domain": profile.get("cv_domain"),
                "resume_query": profile.get("resume_query"),
            }
        except Exception as exc:  # noqa: BLE001
            # #region agent log
            _dbg("H1", "web.py:api_search", "resume parse failed", {"error": str(exc)})
            # #endregion
            return jsonify({"ok": False, "error": f"Resume error: {exc}"}), 400

    # Search query: keywords have priority when present
    if has_query:
        query = expand_search_query(user_query)
    elif has_resume and profile.get("resume_query"):
        query = profile["resume_query"]
    else:
        query = " ".join(
            (profile.get("titles") or [])[:1]
            + (profile.get("preferred_keywords") or profile.get("skills") or [])[:3]
        ) or "developpeur python"

    # Scoring profile for keywords-only: ignore static Mostafa profile.json métier
    score_profile = profile
    if has_query and not has_resume:
        score_profile = profile_from_keywords(user_query, region=region)

    # #region agent log
    _dbg(
        "H2",
        "web.py:api_search",
        "mode resolved",
        {
            "mode": (
                "keywords_only"
                if has_query and not has_resume
                else "hybrid"
                if has_query and has_resume
                else "cv_only"
            ),
            "query": query,
            "cv_domain": score_profile.get("cv_domain"),
            "titles": (score_profile.get("titles") or [])[:5],
            "skills": (score_profile.get("skills") or [])[:8],
            "resume_uploaded": has_resume,
        },
    )
    # #endregion

    # Multi-query: keywords primary; CV terms secondary when both present
    queries = [query]
    if has_query and has_resume and profile.get("resume_query"):
        rq = profile["resume_query"]
        if rq.lower() not in query.lower():
            queries.append(rq)
    elif has_resume and not has_query:
        skills = profile.get("resume_skills_found") or profile.get("skills") or []
        titles = profile.get("resume_titles_found") or profile.get("titles") or []
        if skills:
            if (profile.get("cv_domain") or "") == "it_admin":
                alt = f"administrateur {skills[0]}"
            else:
                alt = f"developpeur {skills[0]}"
            if alt.lower() not in query.lower():
                queries.append(alt)
        if any("backend" in t.lower() for t in titles) and (profile.get("cv_domain") or "") != "it_admin":
            queries.append("backend python")
        if (profile.get("cv_domain") or "") == "it_admin":
            queries.extend(["administrateur systeme", "administrateur reseaux", "technicien informatique"])

    category = score_profile.get("category") or profile.get("category") or "software-dev"
    jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    try:
        for q in queries[:3]:
            batch = search_jobs(
                query=q,
                category=category,
                limit=80,
                region=region,
                max_age_days=max_age_days,
            )
            for job in batch:
                url = (job.get("url") or "").lower()
                key = url or f"{job.get('title')}|{job.get('company')}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                jobs.append(job)
    except Exception as exc:  # noqa: BLE001
        # #region agent log
        _dbg("H4", "web.py:api_search", "search API failed", {"error": str(exc)})
        # #endregion
        return jsonify({"ok": False, "error": f"Job search failed: {exc}"}), 502

    # #region agent log
    _dbg("H2", "web.py:api_search", "queries used", {"queries": queries, "merged_jobs": len(jobs)})
    # #endregion

    if has_query and not has_resume:
        ranked = score_jobs_with_keywords(
            jobs, score_profile, user_query, region=region, keyword_only=True
        )[:limit]
    elif has_query and has_resume:
        ranked = score_jobs_with_keywords(
            jobs, score_profile, user_query, region=region, keyword_only=False
        )[:limit]
    else:
        ranked = score_jobs(jobs, score_profile, region=region)[:limit]

    if use_llm:
        ranked = explain_matches(ranked, score_profile, limit=min(5, len(ranked)))

    # #region agent log
    try:
        _SESSION_DEBUG = Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-90a300.log")
        with _SESSION_DEBUG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "90a300",
                        "runId": "kw-priority-postfix",
                        "hypothesisId": "H1",
                        "location": "web.py:api_search:ranked",
                        "message": "scoring profile used",
                        "data": {
                            "mode": (
                                "keywords_only"
                                if has_query and not has_resume
                                else "hybrid"
                                if has_query and has_resume
                                else "cv_only"
                            ),
                            "user_query": user_query,
                            "effective_query": query,
                            "queries": queries[:3],
                            "cv_domain": score_profile.get("cv_domain"),
                            "score_titles": (score_profile.get("titles") or [])[:3],
                            "score_skills": (score_profile.get("skills") or [])[:6],
                            "excludes": (score_profile.get("exclude_keywords") or [])[:6],
                            "top": [
                                {
                                    "title": (j.get("title") or "")[:60],
                                    "score": j.get("score"),
                                    "reasons": (j.get("match_reasons") or [])[:2],
                                }
                                for j in ranked[:5]
                            ],
                        },
                        "timestamp": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    # Structured JSON payload (no numeric match scores in UI fields)
    ranked = annotate_new(ranked)
    ranked = sort_new_first(ranked)

    results = []
    source_counts: dict[str, int] = {}
    tier_labels = {"morocco": "Maroc", "europe": "International", "international": "International"}
    for job in ranked:
        src = job.get("source") or "unknown"
        source_counts[src] = source_counts.get(src, 0) + 1
        tier = job.get("tier") or SOURCE_TIER.get(src, "international")
        results.append(
            {
                "title": job.get("title"),
                "company": job.get("company"),
                "city": job.get("city") or job.get("location"),
                "location": job.get("location") or job.get("city"),
                "contract_type": job.get("contract_type") or job.get("job_type") or "",
                "salary": job.get("salary") or "",
                "experience": job.get("experience") or "",
                "skills": job.get("skills") or job.get("skill_hits") or [],
                "description": (job.get("description") or "")[:500],
                "url": job.get("url"),
                "application_url": job.get("url"),
                "source": src,
                "source_website": job.get("source_website") or src,
                "publication_date": job.get("publication_date") or "",
                "sort_ts": job.get("sort_ts") or 0,
                "match_percent": job.get("match_percent", job.get("score")),
                "score": job.get("score"),
                "match_reasons": job.get("match_reasons", []),
                "llm_explanation": job.get("llm_explanation"),
                "tier": tier,
                "tier_label": tier_labels.get(tier, tier),
                "remote": bool(job.get("remote")),
                "is_new": bool(job.get("is_new")),
            }
        )

    new_count = sum(1 for j in results if j.get("is_new"))
    marked = mark_seen(ranked)
    out_path = save_results(ranked, query=f"{query} [{region}]")

    # #region agent log
    _dbg(
        "H4",
        "web.py:api_search",
        "search complete",
        {
            "fetched": len(jobs),
            "returned": len(results),
            "new_count": new_count,
            "marked_seen": marked,
            "query": query,
            "region": region,
            "sources": source_counts,
            "saved": str(out_path),
        },
    )
    try:
        _SESSION_DEBUG = Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-90a300.log")
        reg = load_registry()
        with _SESSION_DEBUG.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "90a300",
                        "runId": "expand-live",
                        "hypothesisId": "H2",
                        "location": "web.py:api_search:complete",
                        "message": "live search + novelty",
                        "data": {
                            "returned": len(results),
                            "new_count": new_count,
                            "marked_seen": marked,
                            "sources": source_counts,
                            "registry_ok": [
                                sid
                                for sid, meta in (reg.get("sources") or {}).items()
                                if meta.get("status") == "ok"
                            ][:15],
                            "newly_enabled": reg.get("newly_enabled") or [],
                        },
                        "timestamp": int(time.time() * 1000),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    return jsonify(
        {
            "ok": True,
            "query": query,
            "region": region,
            "region_label": REGION_PRESETS[region]["label"],
            "max_age_days": max_age_days,
            "count": len(results),
            "new_count": new_count,
            "sources_in_results": source_counts,
            "sources_report": LAST_SOURCE_REPORT,
            "resume": resume_meta,
            "results": results,
            "saved_to": str(out_path.name),
        }
    )


def _job_from_form() -> dict[str, Any]:
    return {
        "title": (request.form.get("job_title") or "").strip(),
        "company": (request.form.get("job_company") or "").strip(),
        "city": (request.form.get("job_city") or "").strip(),
        "location": (request.form.get("job_location") or request.form.get("job_city") or "").strip(),
        "description": (request.form.get("job_description") or "").strip(),
        "url": (request.form.get("job_url") or "").strip(),
        "source": (request.form.get("job_source") or "").strip(),
    }


def _profile_and_resume_from_upload() -> tuple[dict[str, Any], str]:
    """Load CV text and build a writing profile from the upload only (not static profile.json identity)."""
    upload = request.files.get("resume")
    if not upload or not upload.filename:
        raise ValueError("Merci d’importer votre CV avant de générer le texte.")
    raw = upload.read()
    resume_text = extract_text(upload.filename, raw)
    if not (resume_text or "").strip():
        raise ValueError("Impossible de lire le CV. Essayez PDF, DOCX ou TXT.")
    base = load_profile()
    profile = profile_for_writing(resume_text, base=base)
    return profile, resume_text

@app.post("/api/generate/cover-letter")
def api_cover_letter():
    try:
        profile, resume_text = _profile_and_resume_from_upload()
        job = _job_from_form()
        if not job.get("title"):
            return jsonify({"ok": False, "error": "Offre incomplete (titre manquant)."}), 400
        # #region agent log
        _dbg("H1", "web.py:api_cover_letter", "request", {"title": job.get("title"), "company": job.get("company")})
        # #endregion
        result = generate_cover_letter(profile, job, resume_text)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Génération impossible: {exc}"}), 500


@app.post("/api/generate/email")
def api_email():
    try:
        profile, resume_text = _profile_and_resume_from_upload()
        job = _job_from_form()
        if not job.get("title"):
            return jsonify({"ok": False, "error": "Offre incomplete (titre manquant)."}), 400
        # #region agent log
        _dbg("H1", "web.py:api_email", "request", {"title": job.get("title"), "company": job.get("company")})
        # #endregion
        result = generate_application_email(profile, job, resume_text)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Génération impossible: {exc}"}), 500


@app.post("/api/linkedin/analyze")
def api_linkedin_analyze():
    """LinkedIn post (paste and/or URL) + CV → match % and reasons."""
    try:
        post = (request.form.get("post") or "").strip()
        url = (request.form.get("url") or "").strip()
        if not post and not url:
            return jsonify(
                {"ok": False, "error": "Collez le texte du post, ou saisissez l’URL LinkedIn."}
            ), 400
        profile, _resume_text = _profile_and_resume_from_upload()
        result = analyze_post_vs_cv(post_text=post, profile=profile, url=url)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Analyse impossible: {exc}"}), 500


@app.post("/api/linkedin/generate")
def api_linkedin_generate():
    """Generate cover letter, email or LinkedIn DM from post paste/URL + CV."""
    try:
        kind = (request.form.get("kind") or "email").strip().lower()
        if kind not in {"email", "linkedin_dm", "cover_letter"}:
            return jsonify(
                {"ok": False, "error": "Choix invalide (lettre, e-mail ou message privé)."}
            ), 400
        post = (request.form.get("post") or "").strip()
        url = (request.form.get("url") or "").strip()
        if not post and not url:
            return jsonify(
                {"ok": False, "error": "Collez le texte du post, ou saisissez l’URL LinkedIn."}
            ), 400
        profile, resume_text = _profile_and_resume_from_upload()
        analysis = analyze_post_vs_cv(post_text=post, profile=profile, url=url)
        job = analysis["job"]
        if kind == "linkedin_dm":
            result = generate_linkedin_message(profile, job, resume_text)
        elif kind == "cover_letter":
            result = generate_cover_letter(profile, job, resume_text)
        else:
            result = generate_application_email(profile, job, resume_text)
        result["match_percent"] = analysis.get("match_percent")
        result["match_reasons"] = analysis.get("match_reasons")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Génération impossible: {exc}"}), 500


@app.post("/api/rewrite")
def api_rewrite():
    """AI rewrite / improve letter, email or LinkedIn DM in the rich editor."""
    try:
        payload = request.get_json(silent=True) or {}
        content = (payload.get("content") or "").strip()
        action = (payload.get("action") or "").strip()
        kind = (payload.get("kind") or "cover_letter").strip()
        context = payload.get("context") or {}
        if not content:
            return jsonify({"ok": False, "error": "Aucun texte à améliorer."}), 400
        if not action:
            return jsonify({"ok": False, "error": "Action d’amélioration manquante."}), 400
        result = rewrite_document(content, action=action, kind=kind, context=context)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Amélioration impossible: {exc}"}), 500


@app.post("/api/export/pdf")
def api_export_pdf():
    """Download generated cover letter / email as PDF."""
    try:
        from job_agent.writing import cover_letter_contacts_ready, html_to_plain

        payload = request.get_json(silent=True) or {}
        content = (payload.get("content") or "").strip()
        title = (payload.get("title") or "").strip()
        kind = (payload.get("kind") or "cover_letter").strip() or "cover_letter"
        if kind == "cover_letter":
            plain = html_to_plain(content) if "<" in content and ">" in content else content
            ready, err = cover_letter_contacts_ready(plain)
            if not ready:
                return jsonify({"ok": False, "error": err}), 400
        # #region agent log
        _session_dbg(
            "H1",
            "web.py:api_export_pdf:entry",
            "pdf export request",
            {
                "kind": kind,
                "title_len": len(title),
                "content_len": len(content),
                "has_accents": any(ord(c) > 127 for c in content[:200]),
            },
        )
        # #endregion
        pdf_bytes, filename = build_letter_pdf(content, title=title, kind=kind)
        # #region agent log
        _session_dbg(
            "H2",
            "web.py:api_export_pdf:built",
            "pdf built",
            {"filename": filename, "pdf_bytes": len(pdf_bytes), "ok": pdf_bytes[:4] == b"%PDF"},
        )
        # #endregion
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except ValueError as exc:
        # #region agent log
        _session_dbg("H3", "web.py:api_export_pdf:value_error", "export validation failed", {"error": str(exc)})
        # #endregion
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        # #region agent log
        _session_dbg("H3", "web.py:api_export_pdf:error", "export failed", {"error": str(exc)})
        # #endregion
        return jsonify({"ok": False, "error": f"Export PDF impossible: {exc}"}), 500


def main() -> None:
    print("Job Finder web UI → http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)


if __name__ == "__main__":
    main()
