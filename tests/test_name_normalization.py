"""Tests for candidate name normalization/formatting in job_agent.resume."""

from __future__ import annotations

import unittest

from job_agent.resume import _clean_person_name, _split_merged_name


class MergedNameSplitTests(unittest.TestCase):
    def test_confident_splits(self) -> None:
        self.assertEqual(_split_merged_name("MOSTAFARAFI"), ("MOSTAFA", "RAFI"))
        self.assertEqual(_split_merged_name("MEHDIRAFI"), ("MEHDI", "RAFI"))

    def test_no_split_when_token_too_short(self) -> None:
        self.assertIsNone(_split_merged_name("ALIA"))

    def test_no_split_when_no_known_given_name_prefix(self) -> None:
        self.assertIsNone(_split_merged_name("XANDERSMITH"))

    def test_no_split_for_a_single_known_mononym(self) -> None:
        # "KHADIJA" is itself a known given name with nothing left over — must not
        # be forced into a bogus split like "KHA" + "DIJA".
        self.assertIsNone(_split_merged_name("KHADIJA"))


class CleanPersonNameTests(unittest.TestCase):
    def test_merged_uppercase_names_are_split_and_formatted(self) -> None:
        self.assertEqual(_clean_person_name("MEHDIRAFI"), "Mehdi RAFI")
        self.assertEqual(_clean_person_name("MOSTAFARAFI"), "Mostafa RAFI")

    def test_two_token_uppercase_name_preserves_family_name_case(self) -> None:
        self.assertEqual(_clean_person_name("ABDELJALIL BAIKARI"), "Abdeljalil BAIKARI")

    def test_already_well_formatted_mixed_case_name_is_preserved(self) -> None:
        self.assertEqual(_clean_person_name("Mostafa RAFI"), "Mostafa RAFI")
        self.assertEqual(_clean_person_name("John Smith"), "John Smith")

    def test_lowercase_name_is_title_cased(self) -> None:
        self.assertEqual(_clean_person_name("mostafa rafi"), "Mostafa Rafi")

    def test_extra_and_duplicated_whitespace_is_removed(self) -> None:
        self.assertEqual(_clean_person_name("  John   Smith  "), "John Smith")

    def test_uncertain_merged_token_keeps_original_rather_than_guessing(self) -> None:
        # No known given-name prefix → must not invent an incorrect split.
        self.assertEqual(_clean_person_name("XANDERSMITH"), "Xandersmith")

    def test_single_known_name_is_not_split(self) -> None:
        self.assertEqual(_clean_person_name("KHADIJA"), "Khadija")


if __name__ == "__main__":
    unittest.main()
