"""Unit tests for job_agent.validators (email / phone / address checks)."""

from __future__ import annotations

import unittest

from job_agent.validators import (
    is_valid_address,
    is_valid_email,
    is_valid_phone,
    normalize_phone,
)


class EmailValidationTests(unittest.TestCase):
    def test_valid_emails(self) -> None:
        for value in ("john@gmail.com", "john.doe@company.co.uk", "  john@gmail.com  "):
            self.assertTrue(is_valid_email(value), value)

    def test_invalid_emails(self) -> None:
        for value in ("hello", "gmail", "john@", "@email.com", "", None):
            self.assertFalse(is_valid_email(value), value)


class PhoneValidationTests(unittest.TestCase):
    def test_normalize_strips_spacing_and_punctuation(self) -> None:
        self.assertEqual(normalize_phone("+212 (0) 6-12-34-56-78"), "+2120612345678")
        self.assertEqual(normalize_phone("06 12 34 56 78"), "0612345678")

    def test_valid_phones(self) -> None:
        for value in ("+212612345678", "06 12 34 56 78", "(0)612345678", "+1 (415) 555-2671"):
            self.assertTrue(is_valid_phone(value), value)

    def test_invalid_phones(self) -> None:
        for value in ("hello", "developer", "1234", "", None):
            self.assertFalse(is_valid_phone(value), value)


class AddressValidationTests(unittest.TestCase):
    def test_valid_addresses(self) -> None:
        for value in (
            "15 Rue Mohammed V Casablanca",
            "Avenue Hassan II Rabat",
            "Hay Salam Agadir",
            "Bloc C Appartement 12",
        ):
            self.assertTrue(is_valid_address(value), value)

    def test_invalid_addresses(self) -> None:
        for value in (
            "Python Developer",
            "Looking for a job",
            "Motivation Letter",
            "Thank you",
            "Software Engineer",
            "",
        ):
            self.assertFalse(is_valid_address(value), value)


if __name__ == "__main__":
    unittest.main()
