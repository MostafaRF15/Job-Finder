"""Format/plausibility validators for candidate contact fields (email, phone, address).

These are intentionally independent, side-effect-free functions: each validator only
answers "is this value plausible?" and never mutates or guesses a value. Callers decide
what to do when a field is missing vs. invalid (see ``job_agent.writing`` for the
cover-letter gate used before PDF export).
"""

from __future__ import annotations

import re

# --- Email ------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def is_valid_email(value: str) -> bool:
    """Return True when ``value`` (leading/trailing spaces ignored) looks like a real email."""
    candidate = (value or "").strip()
    if not candidate:
        return False
    return bool(_EMAIL_PATTERN.match(candidate))


# --- Phone --------------------------------------------------------------

_PHONE_STRIP_PATTERN = re.compile(r"[\s\-()]+")
_PHONE_PATTERN = re.compile(r"^\+?\d{9,15}$")
PHONE_MIN_DIGITS = 9
PHONE_MAX_DIGITS = 15


def normalize_phone(value: str) -> str:
    """Strip spaces, "-", "(" and ")" from a raw phone value (keeps a leading "+")."""
    return _PHONE_STRIP_PATTERN.sub("", (value or "").strip())


def is_valid_phone(value: str) -> bool:
    """Return True when the normalized value has 9-15 digits (optionally "+" prefixed)."""
    normalized = normalize_phone(value)
    if not normalized:
        return False
    return bool(_PHONE_PATTERN.match(normalized))


# --- Address (scoring heuristic — no universal regex exists) ---------------

ADDRESS_KEYWORDS = frozenset(
    {
        "street", "st", "road", "rd", "avenue", "ave", "boulevard", "blvd",
        "route", "rue", "bd", "lot", "lotissement", "résidence", "residence",
        "immeuble", "imm", "bloc", "building", "apartment", "appartement",
        "hay", "quartier", "city",
    }
)
MIN_ADDRESS_LENGTH = 8
ADDRESS_SCORE_THRESHOLD = 2

_ADDRESS_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in ADDRESS_KEYWORDS) + r")\b",
    flags=re.IGNORECASE,
)


def address_validation_score(value: str) -> int:
    """Score ``value`` out of 3 using length / digits / address-keyword heuristics."""
    candidate = (value or "").strip()
    if not candidate:
        return 0
    score = 0
    if len(candidate) >= MIN_ADDRESS_LENGTH:
        score += 1
    if re.search(r"\d", candidate):
        score += 1
    if _ADDRESS_KEYWORD_PATTERN.search(candidate):
        score += 1
    return score


def is_valid_address(value: str) -> bool:
    """Return True when ``value`` scores high enough to plausibly be a real address.

    Free text like "Python Developer" or "Motivation Letter" only ever satisfies at
    most one of the three heuristics below and is therefore rejected.
    """
    return address_validation_score(value) >= ADDRESS_SCORE_THRESHOLD
