"""CLI entrypoint: search → score → explain → save."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow `python -m job_agent` when src is on PYTHONPATH or via -m from project
from job_agent.llm import explain_matches
from job_agent.profile import load_profile
from job_agent.scoring import score_jobs
from job_agent.search import REGION_PRESETS, search_jobs
from job_agent.storage import save_results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Job Finder Agent — search and rank jobs against your profile.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="",
        help="Search keywords (e.g. 'python backend django')",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to profile.json (default: data/profile.json)",
    )
    parser.add_argument(
        "--region",
        choices=sorted(REGION_PRESETS.keys()),
        default=None,
        help="Geographic focus (default: profile.region or morocco)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many top matches to show (default: 10)",
    )
    parser.add_argument(
        "--fetch",
        type=int,
        default=80,
        help="How many jobs to fetch before scoring (default: 80)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM explanations even if OPENAI_API_KEY is set",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)

    profile = load_profile(args.profile)
    query = args.query.strip() or " ".join(profile.get("preferred_keywords", [])[:4])
    category = profile.get("category") or "software-dev"
    region = args.region or profile.get("region") or "morocco"

    print(f"Profile: {profile.get('name', 'User')}")
    print(f"Query:   {query or '(category only)'}")
    print(f"Region:  {REGION_PRESETS.get(region, {}).get('label', region)}")
    print("Fetching jobs for selected zone...")

    try:
        jobs = search_jobs(query=query, category=category, limit=args.fetch, region=region)
    except Exception as exc:  # noqa: BLE001
        print(f"Search failed: {exc}", file=sys.stderr)
        return 1

    print(f"Fetched {len(jobs)} jobs. Scoring against profile...")
    ranked = score_jobs(jobs, profile, region=region)
    top = ranked[: args.limit]

    if not args.no_llm:
        top = explain_matches(top, profile, limit=min(5, len(top)))

    if not top:
        print("No matching jobs after filters. Try broader keywords or edit data/profile.json.")
        return 0

    print("\n=== Top matches ===\n")
    for i, job in enumerate(top, start=1):
        print(f"{i}. [{job['score']}] {job['title']} @ {job['company']}")
        print(f"   Location: {job.get('location') or 'N/A'} · Source: {job.get('source')}")
        print(f"   URL: {job.get('url')}")
        print(f"   Why: {'; '.join(job.get('match_reasons') or [])}")
        if job.get("llm_explanation"):
            print(f"   Note: {job['llm_explanation']}")
        print()

    out_path = save_results(top, query=query)
    print(f"Saved {len(top)} jobs → {out_path}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
