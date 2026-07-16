"""Tests for cover-letter generation: dynamic identity, contact placeholders, date format."""

from __future__ import annotations

import unittest
from datetime import date

from job_agent.writing import (
    CONTACT_ADDRESS_TAG,
    CONTACT_EMAIL_TAG,
    CONTACT_PHONE_TAG,
    _format_french_date,
    contact_block_lines,
    generate_cover_letter,
)

JOB = {"title": "Développeur Python", "company": "Acme Corp", "city": "Casablanca"}


class ContactBlockLinesTests(unittest.TestCase):
    def test_all_fields_present_and_valid(self) -> None:
        contact = {
            "name": "John Smith",
            "address": "15 Rue Mohammed V Casablanca",
            "phone": "+212612345678",
            "email": "john@gmail.com",
        }
        lines = contact_block_lines(contact)
        self.assertEqual(
            lines,
            ["15 Rue Mohammed V Casablanca", "+212612345678", "john@gmail.com"],
        )

    def test_missing_fields_use_placeholders(self) -> None:
        lines = contact_block_lines({"name": "John Smith"})
        self.assertEqual(lines, [CONTACT_ADDRESS_TAG, CONTACT_PHONE_TAG, CONTACT_EMAIL_TAG])

    def test_invalid_fields_use_placeholders_too(self) -> None:
        contact = {"address": "Python Developer", "phone": "hello", "email": "gmail"}
        lines = contact_block_lines(contact)
        self.assertEqual(lines, [CONTACT_ADDRESS_TAG, CONTACT_PHONE_TAG, CONTACT_EMAIL_TAG])

    def test_partial_mix_of_valid_and_missing(self) -> None:
        contact = {"address": "15 Rue Mohammed V Casablanca", "phone": "", "email": "john@gmail.com"}
        lines = contact_block_lines(contact)
        self.assertEqual(lines, ["15 Rue Mohammed V Casablanca", CONTACT_PHONE_TAG, "john@gmail.com"])

    def test_always_returns_exactly_three_lines(self) -> None:
        self.assertEqual(len(contact_block_lines(None)), 3)
        self.assertEqual(len(contact_block_lines({})), 3)


class FrenchDateFormatTests(unittest.TestCase):
    def test_format_matches_spec(self) -> None:
        self.assertEqual(_format_french_date(date(2026, 7, 15)), "Le 15 Juillet 2026")
        self.assertEqual(_format_french_date(date(2026, 1, 1)), "Le 1 Janvier 2026")
        self.assertEqual(_format_french_date(date(2026, 12, 30)), "Le 30 Décembre 2026")
        self.assertEqual(_format_french_date(date(2026, 8, 3)), "Le 3 Août 2026")


class GenerateCoverLetterTemplatePathTests(unittest.TestCase):
    """Uses the deterministic non-LLM template path (no OPENAI_API_KEY in test env)."""

    def test_letter_uses_dynamic_name_from_cv_not_static_profile(self) -> None:
        profile = {"name": "Mostafa", "titles": ["Développeur"], "skills": ["Python"]}
        resume_text = (
            "Marie Dupont\n"
            "15 Rue Mohammed V Casablanca\n"
            "+212612345678\n"
            "marie.dupont@gmail.com\n\n"
            "Développeuse Python\n"
        )
        result = generate_cover_letter(profile, JOB, resume_text)
        content = result["content"]
        self.assertTrue(content.startswith("Marie Dupont"))
        self.assertNotIn("Mostafa", content)

    def test_missing_contact_fields_show_placeholders_only_in_header(self) -> None:
        profile = {"name": "", "titles": ["Développeur"], "skills": ["Python"]}
        resume_text = "John Smith\n\nDéveloppeur Python\n"
        result = generate_cover_letter(profile, JOB, resume_text)
        content = result["content"]
        lines = content.splitlines()
        self.assertEqual(lines[0], "John Smith")
        self.assertEqual(lines[1], CONTACT_ADDRESS_TAG)
        self.assertEqual(lines[2], CONTACT_PHONE_TAG)
        self.assertEqual(lines[3], CONTACT_EMAIL_TAG)
        # Placeholders must never leak into the generated paragraphs / body.
        body = "\n".join(lines[4:])
        self.assertNotIn(CONTACT_ADDRESS_TAG, body)
        self.assertNotIn(CONTACT_PHONE_TAG, body)
        self.assertNotIn(CONTACT_EMAIL_TAG, body)

    def test_letter_date_line_uses_new_format(self) -> None:
        profile = {"name": "", "titles": ["Développeur"], "skills": ["Python"]}
        result = generate_cover_letter(profile, JOB, "John Smith\n\nDéveloppeur Python\n")
        today = _format_french_date()
        self.assertIn(today, result["content"])


if __name__ == "__main__":
    unittest.main()
