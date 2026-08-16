"""Web UI: drafts survive into seen.json, and the HTTP API round-trips.

The server is pointed at a temp users/ tree via a Handler subclass, so the
tests never touch the real users/ directory.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.fetch import Job
from jobhunt.server import Handler
from jobhunt.store import Store

CFG = "seen_file: seen.json\nscore_threshold: 7.0\n"


def _job(job_id: str, score: float | None = 7.5, draft: dict | None = None) -> Job:
    return Job(job_id=job_id, ats="greenhouse", company="Acme", title="Backend Engineer",
               location="Bangalore", url="https://acme.example/job", description="jd",
               score=score, reason="solid spring boot overlap", draft=draft or {})


def _seed(users: Path) -> Path:
    u = users / "alice"
    u.mkdir(parents=True)
    (u / "config.yaml").write_text(CFG, encoding="utf-8")
    store = Store(u / "seen.json")
    store.record([_job("greenhouse:acme:1",
                       draft={"fit_summary": "good", "cover_note": "hello acme"}),
                  _job("greenhouse:acme:2", score=None)], emailed=True)
    return u


# ------------------------------------------------------------- store layer --
def test_record_persists_draft_kit(tmp_path):
    users = tmp_path / "users"
    _seed(users)
    row = Store(users / "alice" / "seen.json").data["greenhouse:acme:1"]
    assert row["draft"]["fit_summary"] == "good"
    assert row["draft"]["cover_note"] == "hello acme"


def test_applied_toggle_and_cover_note_edit(tmp_path):
    users = tmp_path / "users"
    _seed(users)
    store = Store(users / "alice" / "seen.json")
    jid = "greenhouse:acme:2"

    assert store.mark_applied(jid)
    assert store.data[jid]["applied"] and store.data[jid]["applied_on"]

    assert store.unmark_applied(jid)
    assert not store.data[jid]["applied"]
    assert store.data[jid]["applied_on"] is None

    assert store.set_cover_note(jid, "edited note")          # draft created lazily
    assert Store(users / "alice" / "seen.json").data[jid]["draft"]["cover_note"] == "edited note"


# ------------------------------------------------------------ HTTP layer --
class _Api:
    """Tiny client so each test reads like the browser's fetch calls."""

    def __init__(self, users: Path):
        class TestHandler(Handler):
            pass  # class attr override, same trick serve(users_dir=...) uses
        TestHandler.users_dir = users
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.base + path) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path,
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def upload(self, path: str, filename: str, data: bytes) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"X-Filename": filename})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


def test_api_serves_users_jobs_and_applies(tmp_path):
    api = _Api(tmp_path / "users")
    try:
        _seed(tmp_path / "users")

        code, users = api.get("/api/users")
        assert code == 200 and users["users"][0]["name"] == "alice"
        assert users["users"][0]["tracked"] == 2

        code, jobs = api.get("/api/jobs?user=alice")
        assert code == 200
        assert jobs["threshold"] == 7.0 and jobs["stats"]["tracked"] == 2
        assert jobs["jobs"][0]["job_id"] == "greenhouse:acme:1"   # scored first
        assert jobs["jobs"][0]["draft"]["cover_note"] == "hello acme"

        code, body = api.post("/api/applied",
                              {"user": "alice", "job_id": "greenhouse:acme:1",
                               "applied": True})
        assert code == 200 and body["ok"]
        assert Store(tmp_path / "users/alice/seen.json").data["greenhouse:acme:1"]["applied"]

        code, body = api.post("/api/note",
                              {"user": "alice", "job_id": "greenhouse:acme:1",
                               "cover_note": "edited in UI"})
        assert code == 200
        assert (Store(tmp_path / "users/alice/seen.json")
                .data["greenhouse:acme:1"]["draft"]["cover_note"] == "edited in UI")

        # unknown job / unknown user -> 404, not a crash
        code, _ = api.post("/api/applied", {"user": "alice", "job_id": "nope"})
        assert code == 404
        code, _ = api.get("/api/jobs?user=ghost")
        assert code == 404
    finally:
        api.httpd.shutdown()


# ------------------------------------------------------- profile & settings --
def test_resume_upload_and_profile_roundtrip(tmp_path):
    users = tmp_path / "users"
    _seed(users)
    api = _Api(users)
    try:
        # no resume, no profile yet
        code, d = api.get("/api/profile?user=alice")
        assert code == 200 and d["resume"] is None and d["profile"] is None

        # upload replaces: txt in, pdf in, only the pdf survives
        code, d = api.upload("/api/resume?user=alice", "cv.txt", b"skills: go")
        assert code == 200 and d["resume"] == "resume.txt"
        code, d = api.upload("/api/resume?user=alice", "me.pdf", b"%PDF-1.4")
        assert code == 200 and d["resume"] == "resume.pdf"
        assert not (users / "alice" / "resume.txt").exists()

        code, d = api.upload("/api/resume?user=alice", "virus.exe", b"MZ")
        assert code == 400

        # build without a resume is refused (alice has one now: ghost user has not)
        code, d = api.post("/api/profile/build", {"user": "ghost"})
        assert code == 400

        # edit + save profile.json through the API
        code, d = api.post("/api/profile",
                           {"user": "alice", "profile": {"name": "Alice", "core_skills": ["go"]}})
        assert code == 200
        saved = json.loads((users / "alice" / "profile.json").read_text(encoding="utf-8"))
        assert saved == {"name": "Alice", "core_skills": ["go"]}
        code, d = api.get("/api/profile?user=alice")
        assert code == 200 and d["profile"] == saved and d["resume"] == "resume.pdf"

        code, _ = api.post("/api/profile", {"user": "alice", "profile": [1, 2]})
        assert code == 400
    finally:
        api.httpd.shutdown()


def test_env_roundtrip_preserves_custom_keys(tmp_path):
    users = tmp_path / "users"
    _seed(users)
    (users / "alice" / ".env").write_text(
        'GEMINI_API_KEY="old-key"\nCUSTOM_TOKEN=keep-me\n', encoding="utf-8")
    api = _Api(users)
    try:
        code, d = api.get("/api/env?user=alice")
        assert code == 200
        fields = {f["name"]: f for f in d["fields"]}
        assert fields["GEMINI_API_KEY"]["value"] == "old-key"
        assert fields["GEMINI_API_KEY"]["secret"] is True
        assert fields["LLM_PROVIDER"]["value"] == ""      # spec shown even when unset
        assert fields["CUSTOM_TOKEN"]["section"] == "Other"  # unknown key surfaced

        code, d = api.post("/api/env", {"user": "alice", "fields": {
            "GEMINI_API_KEY": "new-key", "LLM_PROVIDER": "gemini",
            "SMTP_PASS": "",  # empty means unset: dropped
        }})
        assert code == 200
        text = (users / "alice" / ".env").read_text(encoding="utf-8")
        assert "GEMINI_API_KEY=new-key" in text
        assert "LLM_PROVIDER=gemini" in text
        assert "CUSTOM_TOKEN=keep-me" in text   # not on the form, still there
        assert "SMTP_PASS" not in text
        # and the file the CLI actually parses agrees
        from jobhunt.userenv import parse_env_file
        env = parse_env_file(users / "alice" / ".env")
        assert env["GEMINI_API_KEY"] == "new-key" and env["CUSTOM_TOKEN"] == "keep-me"
    finally:
        api.httpd.shutdown()
