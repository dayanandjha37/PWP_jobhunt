"""Profile auto-build: resume dropped in the user dir builds profile.json
on the first real run, inside the scoped env (the user's key, not the root's)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt import cli


def _fake_llm(monkeypatch, profile=None, error=None):
    calls = {}

    def fake_resolve(stage):
        calls["stage"] = stage
        return type("P", (), {"name": "stub"}), "stub-model"

    def fake_build(resume_bytes=None, resume_text=None, is_pdf=False,
                   provider=None, model=None):
        calls["bytes"] = resume_bytes
        calls["text"] = resume_text
        if error:
            raise error
        return profile or {"years_experience": 3}

    monkeypatch.setattr(cli, "resolve", fake_resolve)
    monkeypatch.setattr(cli.llm, "build_profile", fake_build)
    return calls


# ------------------------------------------------------------------ _find_resume --

def test_find_resume_globs_resume_dot_anything(tmp_path, monkeypatch):
    """Every supported suffix counts; with several present, sorted() is the tiebreak."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "resume.docx").write_bytes(b"zip bytes")
    assert cli._find_resume({}) == tmp_path / "resume.docx"  # sorts first


def test_find_resume_ignores_wrong_suffixes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.doc").write_bytes(b"old Word binary")
    assert cli._find_resume({}) is None


def test_find_resume_prefers_configured_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.pdf").write_bytes(b"x")
    (tmp_path / "cv.txt").write_text("me")
    assert cli._find_resume({"resume_file": "cv.txt"}).resolve() == (tmp_path / "cv.txt").resolve()


def test_find_resume_missing_configured_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli._find_resume({"resume_file": "nope.pdf"}) is None


def test_find_resume_no_resume_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli._find_resume({}) is None


# ---------------------------------------------------------------- _load_profile --

def test_load_profile_uses_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "profile.json").write_text('{"years_experience": 5}')
    calls = _fake_llm(monkeypatch)  # must not be called
    assert cli._load_profile({"profile_file": "profile.json"}, allow_sample=False)
    assert calls == {}


def test_load_profile_builds_from_resume_on_real_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.txt").write_text("skills: python")
    calls = _fake_llm(monkeypatch)
    profile = cli._load_profile({"profile_file": "profile.json"}, allow_sample=False)
    assert profile == {"years_experience": 3}
    assert calls["text"] == "skills: python"
    written = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert written == profile  # persisted: next run loads it, no second LLM call


def test_load_profile_llm_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.txt").write_text("me")
    from jobhunt.providers import LLMError
    _fake_llm(monkeypatch, error=LLMError("no key set"))
    assert cli._load_profile({}, allow_sample=False) is None
    assert not (tmp_path / "profile.json").exists()


def test_load_profile_mock_run_stays_offline_and_uses_sample(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    calls = _fake_llm(monkeypatch)  # must not be called: --mock makes no LLM calls
    profile = cli._load_profile({}, allow_sample=True)
    assert profile == json.loads(
        (cli.ROOT / "profile.example.json").read_text(encoding="utf-8"))
    assert calls == {}


# ------------------------------------------------------- profile --user <name> --

def _ns(**kw):
    import argparse
    base = {"resume": None, "out": None, "user": None}
    base.update(kw)
    return argparse.Namespace(**base)


def test_profile_user_builds_in_users_env_and_dir(tmp_path, monkeypatch):
    users = tmp_path / "users"
    u = users / "priya"
    u.mkdir(parents=True)
    (u / "config.yaml").write_text(
        "profile_file: profile.json\nfilters:\n  include_titles:\n    - '\\bjava\\b'\n")
    (u / "resume.txt").write_text("skills: kotlin")
    (u / ".env").write_text("GEMINI_API_KEY=priya-key\n")
    monkeypatch.setattr(cli, "USERS_DIR", users)

    seen_env = {}
    calls = _fake_llm(monkeypatch)

    def fake_build(**kw):
        seen_env["key"] = os.environ.get("GEMINI_API_KEY")
        seen_env["cwd"] = os.getcwd()
        return {"name": "Priya", "current_title": "QA Engineer",
                "target_titles": ["QA Engineer", "SDET"], "seniority": "junior"}

    monkeypatch.setattr(cli.llm, "build_profile", fake_build)
    assert cli.cmd_profile(_ns(user="priya")) == 0
    assert seen_env["key"] == "priya-key"          # their .env, scoped
    assert seen_env["cwd"] == str(u)               # relative paths hit their dir
    assert json.loads((u / "profile.json").read_text(encoding="utf-8"))["name"] == "Priya"
    # the same build retunes the config's dynamic filters to the resume
    import yaml as _y
    filters = _y.safe_load((u / "config.yaml").read_text(encoding="utf-8"))["filters"]
    assert filters["include_titles"] == [r"\bqa[\s/\-]+engineer\b", r"\bsdet\b"]
    assert any("senior" in p for p in filters["exclude_titles"])


def test_profile_user_without_resume_fails_clean(tmp_path, monkeypatch):
    users = tmp_path / "users"
    (users / "empty").mkdir(parents=True)
    monkeypatch.setattr(cli, "USERS_DIR", users)
    _fake_llm(monkeypatch)  # must not be called
    assert cli.cmd_profile(_ns(user="empty")) == 1
    assert not (users / "empty" / "profile.json").exists()


def test_profile_user_unknown_name_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "USERS_DIR", tmp_path / "users")
    assert cli.cmd_profile(_ns(user="ghost")) == 1


def test_profile_without_user_needs_resume(tmp_path, monkeypatch):
    assert cli.cmd_profile(_ns()) == 1


# -------------------------------------------------- _build_profile: formats --

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _write_docx(path, paragraphs):
    import zipfile
    body = "".join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>')


def test_build_profile_docx_sends_locally_extracted_text(tmp_path, monkeypatch):
    """.docx works with any provider: cli pulls the text out locally instead
    of asking the API to read a zip."""
    monkeypatch.chdir(tmp_path)
    _write_docx(tmp_path / "resume.docx", ["Ada Lovelace", "skills: python"])
    calls = _fake_llm(monkeypatch)
    assert cli._build_profile(tmp_path / "resume.docx", tmp_path / "profile.json")
    assert calls["bytes"] is None
    assert "skills: python" in calls["text"]


def test_build_profile_pdf_sends_extracted_text_alongside_bytes(tmp_path, monkeypatch):
    """Both travel: bytes for native-PDF providers, extracted text for the rest."""
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)  # real file; reader text stubbed
    calls = _fake_llm(monkeypatch)
    p = tmp_path / "resume.pdf"
    with open(p, "wb") as fh:
        writer.write(fh)
    page = type("Pg", (), {"extract_text": lambda self: "skills: go"})()
    monkeypatch.setattr(pypdf, "PdfReader", lambda path: type("R", (), {"pages": [page]})())
    assert cli._build_profile(p, tmp_path / "profile.json")
    assert calls["bytes"].startswith(b"%PDF")
    assert calls["text"] == "skills: go"


def test_build_profile_scanned_pdf_still_sends_bytes(tmp_path, monkeypatch):
    """No local text layer: bytes alone go out — anthropic/gemini may read the
    scanned page as an image."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 scanned image, no text")
    calls = _fake_llm(monkeypatch)
    assert cli._build_profile(tmp_path / "resume.pdf", tmp_path / "profile.json")
    assert calls["bytes"] == b"%PDF-1.4 scanned image, no text"
    assert calls["text"] is None


def test_build_profile_bad_docx_fails_clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.docx").write_bytes(b"plain text lying about its suffix")
    _fake_llm(monkeypatch)
    assert cli._build_profile(tmp_path / "resume.docx", tmp_path / "profile.json") is None
    assert not (tmp_path / "profile.json").exists()


# ------------------------------------------------------ companies fallback --

def test_companies_file_prefers_the_users_own_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "companies.yaml").write_text("companies: [{ats: lever, slug: a}]\n")
    assert cli._companies_file({}).resolve() == (tmp_path / "companies.yaml").resolve()


def test_companies_file_falls_back_to_shared_root_list(tmp_path, monkeypatch):
    import types
    monkeypatch.chdir(tmp_path)
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    (fake_root / "companies.yaml").write_text("companies: [{ats: lever, slug: b}]\n")
    monkeypatch.setattr(cli, "ROOT", fake_root)
    # cwd has no companies.yaml -> the shared root list is polled instead
    assert cli._companies_file({}) == fake_root / "companies.yaml"


def test_companies_file_missing_everywhere_still_names_the_user_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_root = tmp_path / "root"
    fake_root.mkdir()
    monkeypatch.setattr(cli, "ROOT", fake_root)
    # _cfg raises the helpful "config not found" on this path
    assert cli._companies_file({}) == Path("companies.yaml")
