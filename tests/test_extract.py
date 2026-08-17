"""Local resume text extraction: every provider gets plain text, so resume
format no longer depends on which API reads PDFs."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt import extract

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(path: Path, paragraphs: list[str]) -> None:
    """Minimal but real .docx: the zip layout Word writes, text in w:t runs."""
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>')


def _fake_pdf_reader(monkeypatch, page_texts: list[str]) -> None:
    pypdf = pytest.importorskip("pypdf")  # the fallback tests need the module
    pages = [type("Pg", (), {"extract_text": lambda self, t=t: t})()
             for t in page_texts]
    monkeypatch.setattr(pypdf, "PdfReader", lambda path: type("R", (), {"pages": pages})())


# ------------------------------------------------------------------ dispatch --

def test_txt_and_md_pass_through(tmp_path):
    (tmp_path / "resume.txt").write_text("skills: python")
    (tmp_path / "cv.md").write_text("# me\nskills: kotlin")
    assert extract.resume_text(tmp_path / "resume.txt") == "skills: python"
    assert "skills: kotlin" in extract.resume_text(tmp_path / "cv.md")


def test_unknown_suffix_rejected(tmp_path):
    p = tmp_path / "resume.doc"
    p.write_bytes(b"old Word binary blob")
    with pytest.raises(extract.ExtractError, match=r"\.doc\b"):
        extract.resume_text(p)


# --------------------------------------------------------------------- .docx --

def test_docx_text_one_line_per_paragraph(tmp_path):
    p = tmp_path / "resume.docx"
    _docx(p, ["Ada Lovelace", "Engineer", "skills: analytical engine"])
    assert extract.resume_text(p).splitlines() == [
        "Ada Lovelace", "Engineer", "skills: analytical engine"]


def test_docx_split_runs_join_into_one_line(tmp_path):
    """Word splits a sentence across many w:t runs; only w:p is a line break."""
    body = ('<w:p><w:r><w:t>worked at </w:t></w:r>'
            '<w:r><w:t>X</w:t></w:r></w:p>')
    with zipfile.ZipFile(tmp_path / "resume.docx", "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>')
    assert extract.resume_text(tmp_path / "resume.docx") == "worked at X"


def test_docx_that_is_not_a_zip_fails_clean(tmp_path):
    p = tmp_path / "resume.docx"
    p.write_bytes(b"plain text lying about its suffix")
    with pytest.raises(extract.ExtractError, match="could not read"):
        extract.resume_text(p)


# ---------------------------------------------------------------------- .pdf --

def test_pdf_without_pypdf_installed_says_so(tmp_path, monkeypatch):
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 ...")
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import pypdf -> ImportError
    with pytest.raises(extract.ExtractError, match="pip install pypdf"):
        extract.resume_text(p)


def test_pdf_garbage_fails_clean(tmp_path):
    pytest.importorskip("pypdf")
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 not actually a pdf")
    with pytest.raises(extract.ExtractError, match="could not read"):
        extract.resume_text(p)


def test_pdf_with_text_layer_extracts(tmp_path, monkeypatch):
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 fake; the reader is stubbed below")
    _fake_pdf_reader(monkeypatch, ["skills: python"])
    assert extract.resume_text(p) == "skills: python"


def test_pdf_without_text_layer_says_scanned(tmp_path, monkeypatch):
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 scanned image")
    _fake_pdf_reader(monkeypatch, ["", ""])
    with pytest.raises(extract.ExtractError, match="no text layer"):
        extract.resume_text(p)
