"""Export generated letters / emails as PDF."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
)
_FONT_BOLD_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
)


def _pick_font(candidates: tuple[Path, ...]) -> Path | None:
    for path in candidates:
        if path.is_file():
            return path
    return None


def _safe_filename(title: str, kind: str) -> str:
    base = (title or kind or "document").strip().lower()
    base = re.sub(r"[^\w\-]+", "_", base, flags=re.UNICODE)
    base = re.sub(r"_+", "_", base).strip("_") or "document"
    prefix = "lettre" if kind == "cover_letter" else "email" if kind == "email" else "document"
    return f"{prefix}_{base[:50]}.pdf"


def build_letter_pdf(
    content: str,
    *,
    title: str = "",
    kind: str = "cover_letter",
) -> tuple[bytes, str]:
    """Return (pdf_bytes, download_filename). Accepts plain text or simple HTML."""
    from job_agent.writing import html_to_plain

    raw = (content or "").strip()
    if "<" in raw and ">" in raw:
        text = html_to_plain(raw)
    else:
        text = raw
    if not text:
        raise ValueError("Aucun texte à exporter.")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(left=18, top=18, right=18)
    pdf.add_page()

    regular = _pick_font(_FONT_CANDIDATES)
    bold = _pick_font(_FONT_BOLD_CANDIDATES)
    if regular:
        pdf.add_font("LetterFont", "", str(regular))
        if bold:
            pdf.add_font("LetterFont", "B", str(bold))
        pdf.set_font("LetterFont", size=11)
    else:
        pdf.set_font("Helvetica", size=11)

    # Print with optional bold large name on first line (cover letters)
    paragraphs = text.split("\n")
    if kind == "cover_letter":
        # First non-empty line = candidate name → bold + large
        for i, line in enumerate(paragraphs):
            if line.strip():
                if regular:
                    pdf.set_font("LetterFont", "B" if bold else "", 16)
                else:
                    pdf.set_font("Helvetica", "B", 16)
                pdf.multi_cell(0, 8, line.strip())
                pdf.ln(2)
                paragraphs = paragraphs[i + 1 :]
                break
        if regular:
            pdf.set_font("LetterFont", size=11)
        else:
            pdf.set_font("Helvetica", size=11)

    body = "\n".join(paragraphs).lstrip("\n")
    if body.strip():
        pdf.multi_cell(0, 6.5, body)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue(), _safe_filename(title, kind)
