"""Local web UI: review drafts, edit the note, mark applied, kick off runs.

Stdlib only (http.server) so the demo needs no extra install — same ethos as
the .env loader. It binds 127.0.0.1 only: it can read your configs and start
pipeline runs, so it stays on your machine.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from .cli import RESUME_SUFFIXES
from .page import PAGE
from .store import Store
from .userenv import parse_env_file

ROOT = Path(__file__).resolve().parent.parent
USERS_DIR = ROOT / "users"


# ----------------------------------------------------------------- run state --
class ProcState:
    """One subprocess at a time per slot; the browser polls for its log."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.user: str | None = None
        self.rc: int | None = None
        self.log: deque[str] = deque(maxlen=400)

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, user: str, cmd: list[str]) -> bool:
        with self.lock:
            if self.running:
                return False
            self.user = user
            self.rc = None
            self.log.clear()
            self.log.append("$ " + " ".join(cmd) + "\n")
            self.thread = threading.Thread(target=self._run, args=(cmd,), daemon=True)
            self.thread.start()
            return True

    def _run(self, cmd: list[str]) -> None:
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                cmd, cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.log.append(line)
            self.rc = proc.wait()
        except Exception as e:  # never kill the UI process
            self.log.append(f"! run crashed ({type(e).__name__}: {e})\n")
            self.rc = 1

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "user": self.user,
            "rc": self.rc,
            "log": "".join(self.log)[-8000:],
        }


RUN = ProcState()    # python -m jobhunt run-all --user <name>
BUILD = ProcState()  # python -m jobhunt profile  --user <name>


# ------------------------------------------------------------------ env spec --
# What the Settings tab shows, in write order. Keys found in the user's .env
# but not listed here are still surfaced (marked secret) and preserved on save.
ENV_SPEC: list[tuple[str, list[tuple[str, str, bool]]]] = [
    ("LLM", [
        ("LLM_PROVIDER", "provider for every stage (anthropic / gemini / groq / ollama / openai-compatible)", False),
        ("SCREEN_PROVIDER", "screen-stage provider override", False),
        ("SCREEN_MODEL", "screen-stage model", False),
        ("DRAFT_PROVIDER", "draft-stage provider override", False),
        ("DRAFT_MODEL", "draft-stage model", False),
        ("LLM_BASE_URL", "openai-compatible base URL", False),
        ("OLLAMA_HOST", "ollama host (local only)", False),
        ("GEMINI_API_KEY", "Gemini API key", True),
        ("ANTHROPIC_API_KEY", "Anthropic API key", True),
        ("GROQ_API_KEY", "Groq / openai-compatible API key", True),
    ]),
    ("Email digest", [
        ("SMTP_HOST", "SMTP host (Gmail: smtp.gmail.com)", False),
        ("SMTP_PORT", "SMTP port (Gmail: 587)", False),
        ("SMTP_USER", "SMTP login - your email", False),
        ("SMTP_PASS", "SMTP password - Gmail App Password, not the login", True),
        ("MAIL_TO", "digest recipient (defaults to SMTP_USER)", False),
    ]),
]


def _env_fields(env: dict[str, str]) -> list[dict]:
    fields = []
    for section, specs in ENV_SPEC:
        for name, label, secret in specs:
            fields.append({"name": name, "label": label, "section": section,
                           "secret": secret, "value": env.get(name, "")})
    listed = {f["name"] for f in fields}
    for name, value in env.items():  # custom keys: surfaced and kept on save
        if name not in listed:
            fields.append({"name": name, "label": name, "section": "Other",
                           "secret": True, "value": value})
    return fields


def _env_line(value: str) -> str:
    value = str(value).strip()
    if any(c in value for c in ' \t#"\''):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _write_env(path: Path, env: dict[str, str]) -> None:
    """Render the env dict as a commented KEY=VALUE file. Empty values are
    omitted: the loaders treat an empty value as unset anyway."""
    lines = ["# Managed by the jobhunt UI. Plain KEY=VALUE lines, # comments."]
    listed = []
    for section, specs in ENV_SPEC:
        block = [f"{name}={_env_line(env[name])}" for name, _, _ in specs
                 if env.get(name)]
        listed += [name for name, _, _ in specs]
        if block:
            lines += ["", f"# --- {section} ---", *block]
    extra = [f"{k}={_env_line(v)}" for k, v in env.items()
             if k not in listed and v]
    if extra:
        lines += ["", "# --- other ---", *extra]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -------------------------------------------------------------------- data --
def _users(users_dir: Path) -> list[dict]:
    out = []
    if users_dir.is_dir():
        for d in sorted(users_dir.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists():
                cfg = yaml.safe_load((d / "config.yaml").read_text(encoding="utf-8")) or {}
                seen = d / cfg.get("seen_file", "seen.json")
                out.append({"name": d.name, "tracked": Store(seen).stats()["tracked"]})
    return out


def _user_dir(users_dir: Path, name: str) -> Path | None:
    u = users_dir / name
    if u.is_dir() and (u / "config.yaml").exists():
        return u
    return None


def _jobs_payload(users_dir: Path, name: str) -> dict:
    u = _user_dir(users_dir, name)
    if u is None:
        return {"error": f"no user directory: {name}"}
    cfg = yaml.safe_load((u / "config.yaml").read_text(encoding="utf-8")) or {}
    store = Store(u / cfg.get("seen_file", "seen.json"))
    jobs = [{"job_id": jid, **row} for jid, row in store.data.items()]
    # best first: score desc (unscored last), then newest
    jobs.sort(key=lambda j: (j.get("score") is None,
                             -(j.get("score") or 0),
                             j.get("first_seen") or ""), reverse=False)
    return {
        "user": name,
        "threshold": float(cfg.get("score_threshold", 7.0)),
        "stats": store.stats(),
        "jobs": jobs,
    }


def _find_resume_file(u: Path, cfg: dict) -> str | None:
    """The resume the CLI would pick for this user: cfg resume_file if set,
    else the first resume.* in their directory (same glob as cli._find_resume)."""
    name = cfg.get("resume_file")
    if name and (u / name).exists():
        return name
    for p in sorted(u.glob("resume.*")):
        if p.suffix.lower() in RESUME_SUFFIXES:
            return p.name
    return None


def _profile_payload(users_dir: Path, name: str) -> dict:
    u = _user_dir(users_dir, name)
    if u is None:
        return {"error": f"no user directory: {name}"}
    cfg = yaml.safe_load((u / "config.yaml").read_text(encoding="utf-8")) or {}
    profile_file = cfg.get("profile_file", "profile.json")
    profile = None
    pf = u / profile_file
    if pf.exists():
        try:
            profile = json.loads(pf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {"error": f"{profile_file} is not valid JSON: {e}"}
    return {"user": name, "resume": _find_resume_file(u, cfg), "profile": profile}


# ----------------------------------------------------------------- handler --
class Handler(BaseHTTPRequestHandler):
    """Class attrs so tests can point the whole UI at a temp users/ tree."""
    users_dir = USERS_DIR

    # ---- plumbing ----
    def log_message(self, fmt, *args):  # quiet console; the UI is the log
        pass

    def _send(self, code: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routes ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, PAGE, ctype="text/html")
        elif path == "/api/users":
            self._json(200, {"users": _users(self.users_dir)})
        elif path == "/api/jobs":
            name = self._query().get("user", "")
            payload = _jobs_payload(self.users_dir, name)
            self._json(200 if "error" not in payload else 404, payload)
        elif path == "/api/run/status":
            self._json(200, RUN.snapshot())
        elif path == "/api/profile":
            payload = _profile_payload(self.users_dir, self._query().get("user", ""))
            self._json(200 if "error" not in payload else 404, payload)
        elif path == "/api/build/status":
            self._json(200, BUILD.snapshot())
        elif path == "/api/env":
            payload = self._env_payload(self._query().get("user", ""))
            self._json(200 if "error" not in payload else 404, payload)
        else:
            self._json(404, {"error": f"no route: {path}"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/applied":
                self._post_applied(self._body())
            elif path == "/api/note":
                self._post_note(self._body())
            elif path == "/api/run":
                self._post_run(self._body())
            elif path == "/api/resume":
                self._post_resume()
            elif path == "/api/profile":
                self._post_profile(self._body())
            elif path == "/api/profile/build":
                self._post_build(self._body())
            elif path == "/api/env":
                self._post_env(self._body())
            else:
                self._json(404, {"error": f"no route: {path}"})
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            self._json(400, {"error": f"bad request: {e}"})

    def _query(self) -> dict:
        if "?" not in self.path:
            return {}
        from urllib.parse import parse_qs
        q = parse_qs(self.path.split("?", 1)[1])
        return {k: v[0] for k, v in q.items()}

    # ---- actions ----
    def _store_for(self, body: dict) -> tuple[Store, str]:
        u = _user_dir(self.users_dir, str(body.get("user") or ""))
        if u is None:
            raise ValueError(f"no user directory: {body.get('user')}")
        cfg = yaml.safe_load((u / "config.yaml").read_text(encoding="utf-8")) or {}
        return Store(u / cfg.get("seen_file", "seen.json")), str(body["job_id"])

    def _post_applied(self, body: dict) -> None:
        store, job_id = self._store_for(body)
        if body.get("applied", True):
            ok = store.mark_applied(job_id)
        else:
            ok = store.unmark_applied(job_id)
        self._json(200 if ok else 404, {"ok": ok} if ok else {"error": f"unknown job_id: {job_id}"})

    def _post_note(self, body: dict) -> None:
        store, job_id = self._store_for(body)
        ok = store.set_cover_note(job_id, str(body.get("cover_note", "")))
        self._json(200 if ok else 404, {"ok": ok} if ok else {"error": f"unknown job_id: {job_id}"})

    def _post_run(self, body: dict) -> None:
        u = _user_dir(self.users_dir, str(body.get("user") or ""))
        if u is None:
            raise ValueError(f"no user directory: {body.get('user')}")
        cmd = [sys.executable, "-m", "jobhunt", "run-all", "--user", u.name]
        if body.get("mock"):
            cmd += ["--mock", "--scorer", "keyword"]
        if not RUN.start(u.name, cmd):
            self._json(409, {"error": "a run is already in progress"})
            return
        self._json(200, {"ok": True, "started": True})

    # ---- profile & settings ----
    def _post_resume(self) -> None:
        """Raw file upload (not JSON): the bytes are the body, the name rides
        in an X-Filename header. One resume per user — an upload replaces any
        previous one so the CLI glob never sees two candidates."""
        name = self._query().get("user", "")
        u = _user_dir(self.users_dir, name)
        if u is None:
            self._json(404, {"error": f"no user directory: {name}"})
            return
        filename = Path(self.headers.get("X-Filename") or "resume").name
        if filename and Path(filename).suffix.lower() not in RESUME_SUFFIXES:
            self._json(400, {"error": f"unsupported type: {filename} "
                              f"(want {'/'.join(RESUME_SUFFIXES)})"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        if not data:
            self._json(400, {"error": "empty upload"})
            return
        cfg = yaml.safe_load((u / "config.yaml").read_text(encoding="utf-8")) or {}
        target = cfg.get("resume_file") or f"resume{Path(filename).suffix.lower()}"
        if not cfg.get("resume_file"):  # clear stale resume.* so the glob is unambiguous
            for p in u.glob("resume.*"):
                if p.suffix.lower() in RESUME_SUFFIXES and p.name != target:
                    p.unlink()
        (u / target).write_bytes(data)
        self._json(200, {"ok": True, "resume": target, "bytes": len(data)})

    def _post_profile(self, body: dict) -> None:
        u = _user_dir(self.users_dir, str(body.get("user") or ""))
        if u is None:
            raise ValueError(f"no user directory: {body.get('user')}")
        profile = body.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("profile must be a JSON object")
        cfg = yaml.safe_load((u / "config.yaml").read_text(encoding="utf-8")) or {}
        out = u / cfg.get("profile_file", "profile.json")
        out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        self._json(200, {"ok": True, "saved": out.name})

    def _post_build(self, body: dict) -> None:
        u = _user_dir(self.users_dir, str(body.get("user") or ""))
        if u is None:
            raise ValueError(f"no user directory: {body.get('user')}")
        if not _find_resume_file(u, yaml.safe_load(
                (u / "config.yaml").read_text(encoding="utf-8")) or {}):
            self._json(400, {"error": "upload a resume first"})
            return
        cmd = [sys.executable, "-m", "jobhunt", "profile", "--user", u.name]
        if not BUILD.start(u.name, cmd):
            self._json(409, {"error": "a profile build is already in progress"})
            return
        self._json(200, {"ok": True, "started": True})

    def _env_payload(self, name: str) -> dict:
        u = _user_dir(self.users_dir, name)
        if u is None:
            return {"error": f"no user directory: {name}"}
        env = parse_env_file(u / ".env")
        return {"user": name, "fields": _env_fields(env)}

    def _post_env(self, body: dict) -> None:
        u = _user_dir(self.users_dir, str(body.get("user") or ""))
        if u is None:
            raise ValueError(f"no user directory: {body.get('user')}")
        fields = body.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object of NAME -> value")
        env = parse_env_file(u / ".env")  # custom keys not on the form survive
        env.update({str(k): str(v).strip() for k, v in fields.items()})
        _write_env(u / ".env", env)
        self._json(200, {"ok": True})


# ------------------------------------------------------------------ serve --
def serve(port: int = 8765, default_user: str | None = None,
          open_browser: bool = True, users_dir: Path | None = None) -> None:
    if users_dir is not None:
        Handler.users_dir = users_dir
    url = f"http://127.0.0.1:{port}/"
    if default_user:
        url += f"?user={default_user}"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"jobhunt UI: {url}   (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
