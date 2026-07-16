"""Auto registry of recruitment sources: learn what works and retry later."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "sources_status.json"
# Re-probe unavailable / broken sources at most once per day
PROBE_COOLDOWN_SEC = 24 * 3600


def load_registry() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"sources": {}, "updated_at": None}
    try:
        with DATA_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("sources", {})
        return data
    except Exception:
        return {"sources": {}, "updated_at": None}


def save_registry(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def update_from_report(report: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge live Morocco (or multi) source report into persistent registry."""
    data = load_registry()
    store = data.setdefault("sources", {})
    now = datetime.now(timezone.utc).isoformat()
    newly_ok: list[str] = []
    for row in report:
        sid = row.get("id") or row.get("source")
        if not sid:
            continue
        prev = store.get(sid) or {}
        status = row.get("status") or "unknown"
        jobs_found = int(row.get("jobs_found") or 0)
        entry = {
            "name": row.get("name") or prev.get("name") or sid,
            "url": row.get("url") or prev.get("url") or "",
            "status": status,
            "jobs_found": jobs_found,
            "last_checked": now,
            "note": (row.get("note") or "")[:200],
            "enabled": bool(prev.get("enabled")) or status == "ok",
            "successes": int(prev.get("successes") or 0),
            "failures": int(prev.get("failures") or 0),
        }
        if status == "ok":
            entry["successes"] += 1
            entry["last_ok"] = now
            entry["enabled"] = True
            if not prev.get("enabled") and prev.get("status") != "ok":
                newly_ok.append(sid)
        elif status in {"unavailable", "error", "blocked"}:
            entry["failures"] += 1
            entry["last_fail"] = now
        store[sid] = entry
    data["newly_enabled"] = newly_ok
    save_registry(data)
    return data


def enabled_extra_parsers() -> list[str]:
    """Site ids that were auto-enabled and should be tried if a parser exists."""
    store = load_registry().get("sources") or {}
    return [sid for sid, meta in store.items() if meta.get("enabled") and meta.get("status") == "ok"]


def should_retry(site_id: str) -> bool:
    meta = (load_registry().get("sources") or {}).get(site_id) or {}
    status = meta.get("status") or "not_implemented"
    if status == "ok":
        return True
    last = meta.get("last_checked")
    if not last:
        return True
    try:
        # rough ISO parse
        ts = datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
    except Exception:
        return True
    return (time.time() - ts) >= PROBE_COOLDOWN_SEC


def mark_parser_result(site_id: str, name: str, url: str, ok: bool, jobs_found: int, note: str = "") -> None:
    data = load_registry()
    store = data.setdefault("sources", {})
    prev = store.get(site_id) or {}
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "name": name or prev.get("name") or site_id,
        "url": url or prev.get("url") or "",
        "status": "ok" if ok else "error",
        "jobs_found": jobs_found,
        "last_checked": now,
        "note": note[:200],
        "enabled": True if ok else bool(prev.get("enabled")),
        "successes": int(prev.get("successes") or 0) + (1 if ok else 0),
        "failures": int(prev.get("failures") or 0) + (0 if ok else 1),
    }
    if ok:
        entry["last_ok"] = now
        entry["enabled"] = True
    else:
        entry["last_fail"] = now
    store[site_id] = entry
    save_registry(data)
