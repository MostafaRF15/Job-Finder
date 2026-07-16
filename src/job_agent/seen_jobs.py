"""Remember which job offers were already shown (nouveautés)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "seen_jobs.json"


def job_fingerprint(job: dict[str, Any]) -> str:
    url = (job.get("url") or job.get("application_url") or "").strip().lower()
    if url:
        return re.sub(r"[#?].*$", "", url).rstrip("/")
    title = (job.get("title") or "").strip().lower()
    company = (job.get("company") or "").strip().lower()
    source = (job.get("source") or "").strip().lower()
    return f"{source}|{company}|{title}"


def load_seen() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"jobs": {}}
    try:
        with DATA_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"jobs": {}}
        data.setdefault("jobs", {})
        return data
    except Exception:
        return {"jobs": {}}


def save_seen(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def annotate_new(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = load_seen().get("jobs") or {}
    out: list[dict[str, Any]] = []
    for job in jobs:
        item = dict(job)
        fp = job_fingerprint(item)
        item["fingerprint"] = fp
        item["is_new"] = fp not in seen
        out.append(item)
    return out


def sort_new_first(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        jobs,
        key=lambda j: (
            0 if j.get("is_new") else 1,
            -(j.get("score") or j.get("match_percent") or 0),
            -(j.get("sort_ts") or 0),
        ),
    )


def mark_seen(jobs: list[dict[str, Any]]) -> int:
    data = load_seen()
    store = data.setdefault("jobs", {})
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for job in jobs:
        fp = job.get("fingerprint") or job_fingerprint(job)
        if not fp:
            continue
        if fp not in store:
            store[fp] = {"first_seen": now, "title": (job.get("title") or "")[:120], "source": job.get("source")}
            added += 1
        store[fp]["last_seen"] = now
    # Cap growth to avoid unbounded file
    if len(store) > 5000:
        oldest = sorted(store.items(), key=lambda kv: kv[1].get("last_seen") or "")[: len(store) - 4000]
        for key, _ in oldest:
            store.pop(key, None)
    save_seen(data)
    return added
