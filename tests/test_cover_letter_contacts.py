"""Tests for the PDF-export contact gate in job_agent.writing."""

from __future__ import annotations

import unittest

from job_agent.writing import cover_letter_contacts_ready


VALID_LETTER = """John Doe
15 Rue Mohammed V Casablanca
+212 6 12 34 56 78
john@gmail.com

Objet : Candidature au poste de Développeur

Madame, Monsieur,

Je vous écris pour...
"""

INVALID_LETTER = """John Doe
Python Developer
hello
gmail

Objet : Candidature au poste de Développeur

Madame, Monsieur,

Je vous écris pour...
"""


class CoverLetterContactsReadyTests(unittest.TestCase):
    def test_valid_contacts_pass(self) -> None:
        ready, err = cover_letter_contacts_ready(VALID_LETTER)
        self.assertTrue(ready, err)
        self.assertEqual(err, "")

    def test_garbage_contacts_are_blocked(self) -> None:
        ready, err = cover_letter_contacts_ready(INVALID_LETTER)
        self.assertFalse(ready)
        self.assertIn("adresse complète valide", err)
        self.assertIn("téléphone valide", err)
        self.assertIn("e-mail valide", err)

    def test_missing_contacts_are_blocked(self) -> None:
        ready, err = cover_letter_contacts_ready("John Doe\n\nObjet : Candidature\n\nMadame,\n")
        self.assertFalse(ready)
        self.assertIn("Veuillez renseigner votre adresse complète.", err)


if __name__ == "__main__":
    unittest.main()
