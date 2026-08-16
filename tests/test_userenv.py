"""Env scoping for multi-user runs: override, restore, no leak between users."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.userenv import env_scope, parse_env_file


def test_parse_env_file_reads_keys_and_strips_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment line\n"
        "GEMINI_API_KEY=abc123\n"
        'SMTP_USER="you@gmail.com"\n'
        "MAIL_TO='friend@gmail.com'\n"
        "\n"
        "not-a-line\n",
        encoding="utf-8")
    assert parse_env_file(p) == {
        "GEMINI_API_KEY": "abc123",
        "SMTP_USER": "you@gmail.com",
        "MAIL_TO": "friend@gmail.com",
    }


def test_parse_env_file_missing_returns_empty(tmp_path):
    assert parse_env_file(tmp_path / "nope") == {}


def test_env_scope_overrides_and_restores(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "root-key")
    monkeypatch.delenv("NEW_KEY", raising=False)

    with env_scope({"GEMINI_API_KEY": "user-key", "NEW_KEY": "fresh"}):
        assert os.environ["GEMINI_API_KEY"] == "user-key"   # override, not setdefault
        assert os.environ["NEW_KEY"] == "fresh"

    assert os.environ["GEMINI_API_KEY"] == "root-key"       # previous value back
    assert "NEW_KEY" not in os.environ                       # introduced key gone


def test_env_scope_restores_on_exception(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        with env_scope({"GEMINI_API_KEY": "user-key"}):
            raise RuntimeError("pipeline blew up")
    except RuntimeError:
        pass
    assert "GEMINI_API_KEY" not in os.environ


def test_no_leak_between_users(monkeypatch):
    """user 1 defines a key user 2 must never see — the reason env_scope
    overrides instead of setdefault."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with env_scope({"ANTHROPIC_API_KEY": "user1-key"}):
        pass
    with env_scope({}):  # user 2 has no .env entries for this key
        assert "ANTHROPIC_API_KEY" not in os.environ
