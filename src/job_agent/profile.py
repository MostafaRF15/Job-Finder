"""Load and validate the user job-search profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[2] / "data" / "profile.json"


def load_profile(path: Path | str | None = None) -> dict[str, Any]:
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with profile_path.open(encoding="utf-8") as f:
        profile = json.load(f)

    required = ["titles", "skills"]
    missing = [key for key in required if key not in profile]
    if missing:
        raise ValueError(f"Profile missing required keys: {', '.join(missing)}")

    profile.setdefault("exclude_keywords", [])
    profile.setdefault("preferred_keywords", [])
    profile.setdefault("locations", ["Remote"])
    profile.setdefault("category", "software-dev")
    return profile
