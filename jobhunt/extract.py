"""Local resume text extraction.

Only Anthropic and Gemini read PDFs natively; nobody reads .docx over the
chat APIs. Rather than gate resume formats on the provider, pull the text
out locally and send plain text like any .txt resume: .docx is just a zip
of XML (stdlib handles it), .pdf needs pypdf (lazy-imported so mock runs
and .txt users never install it).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

TEXT_SUFFIXES = (".txt", ".md")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ExtractError(ValueError):
    """The resume file exists but no text could be pulled out of it."""


def resume_text(path: str | Path) -> str:
    """Resume file (.pdf/.docx/.txt/.md) -> plain text for the LLM prompt."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return p.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _pdf_text(p)
    if suffix == ".docx":
        return _docx_text(p)
    raise ExtractError(f"unsupported resume type: {suffix} "
                       f"(want .pdf/.docx/{'/'.join(TEXT_SUFFIXES)})")


def _pdf_text(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ExtractError("PDF resumes need pypdf — pip install pypdf "
                           "(or export the resume to .txt/.md)") from None
    try:
        pages = [page.extract_text() or "" for page in PdfReader(str(p)).pages]
    except Exception as e:  # pypdf raises a zoo of parse errors on garbage
        raise ExtractError(f"could not read {p.name}: {e}") from e
    text = "\n".join(pages).strip()
    if not text:
        # Scanned image PDF: the words are pixels, not characters.
        raise ExtractError(f"{p.name} has no text layer (scanned image?) — "
                           f"export it to .txt/.md instead")
    return text


def _docx_text(p: Path) -> str:
    try:
        with zipfile.ZipFile(p) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise ExtractError(f"could not read {p.name} as .docx: {e}") from e
    # One line per paragraph; text lives in w:t runs inside w:p paragraphs.
    lines = ["".join(t.text or "" for t in para.iter(f"{_W}t"))
             for para in root.iter(f"{_W}p")]
    return "\n".join(lines).strip()
