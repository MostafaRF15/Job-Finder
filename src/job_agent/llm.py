"""Optional LLM explanations for top job matches."""

from __future__ import annotations

import os
from typing import Any


def explain_matches(jobs: list[dict[str, Any]], profile: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """Add a short LLM explanation when OPENAI_API_KEY is set; otherwise no-op."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        for job in jobs[:limit]:
            job.setdefault(
                "llm_explanation",
                "LLM disabled — using rule-based reasons only. Set OPENAI_API_KEY for richer notes.",
            )
        return jobs

    try:
        from openai import OpenAI
    except ImportError:
        return jobs

    client = OpenAI(api_key=api_key)
    name = profile.get("name", "candidate")
    skills = ", ".join(profile.get("skills", [])[:12])
    titles = ", ".join(profile.get("titles", [])[:5])

    for job in jobs[:limit]:
        prompt = (
            f"Candidate: {name}. Target titles: {titles}. Skills: {skills}.\n"
            f"Job: {job.get('title')} at {job.get('company')}. "
            f"Location: {job.get('location')}. Score: {job.get('score')}.\n"
            f"Known match reasons: {', '.join(job.get('match_reasons') or [])}.\n"
            "Write 2 short sentences: why this job may fit, and one caution. No fluff."
        )
        try:
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a concise job-match assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=120,
                temperature=0.3,
            )
            job["llm_explanation"] = (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 — keep agent usable if API fails
            job["llm_explanation"] = f"LLM explanation unavailable ({exc.__class__.__name__})."

    return jobs
