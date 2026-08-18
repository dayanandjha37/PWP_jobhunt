"""jobhunt CLI: profile -> fetch -> prefilter -> screen -> draft -> digest -> mail.

The agent never submits an application. It finds, filters, ranks and drafts.
A human reads the digest, edits the note, and presses submit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from . import digest as digest_mod
from . import extract
from . import filtergen
from . import ingest, llm, mailer
from .fetch import fetch_all
from .mock import fetch_all_mock
from .prefilter import prefilter
from .providers import LLMError, resolve
from .store import Store
from .userenv import env_scope, parse_env_file

ROOT = Path(__file__).resolve().parent.parent
USERS_DIR = ROOT / "users"


def _load_env(path: str = ".env") -> None:
    """Minimal .env reader so there is no python-dotenv dependency."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cfg(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"config not found: {p}  (run from the project root)")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


RESUME_SUFFIXES = (".pdf", ".docx", ".txt", ".md")


def _find_resume(cfg: dict) -> Path | None:
    """Locate the user's resume: cfg resume_file if set, else resume.* in cwd."""
    name = cfg.get("resume_file")
    if name:
        p = Path(name)
        return p if p.exists() else None
    for p in sorted(Path.cwd().glob("resume.*")):
        if p.suffix.lower() in RESUME_SUFFIXES:
            return p
    return None


def _companies_file(cfg: dict) -> Path:
    """The boards list to poll: the user's own companies_file when present,
    else the shared root list — one master for everyone, a per-user file
    only as an override."""
    p = Path(cfg.get("companies_file", "companies.yaml"))
    if p.exists():
        return p
    shared = ROOT / p.name
    return shared if shared.exists() else p


def _build_profile(src: Path, out: Path, cfg_path: Path | None = None) -> dict | None:
    """Resume file -> profile dict, written to `out`. Uses the scoped env,
    so under run-all this is the current user's key, not the root one.
    With cfg_path, also retunes that config's dynamic filters to the resume."""
    is_pdf = src.suffix.lower() == ".pdf"
    # Local text extraction: works for every provider, not just the two that
    # read PDFs natively. A PDF with no text layer still goes as bytes — the
    # native-PDF providers may salvage a scanned page as an image.
    try:
        resume_text = extract.resume_text(src)
    except extract.ExtractError as e:
        if not is_pdf:
            print(f"  ! profile build failed: {e}")
            return None
        resume_text = None
    try:
        provider, model = resolve("draft")
        print(f"  building profile from {src.name} via {provider.name}/{model} ...")
        profile = llm.build_profile(
            resume_bytes=src.read_bytes() if is_pdf else None,
            resume_text=resume_text,
            is_pdf=is_pdf, provider=provider, model=model,
        )
    except (LLMError, ValueError) as e:
        print(f"  ! profile build failed: {e}")
        return None
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"  wrote {out}")
    if cfg_path is not None and filtergen.sync_filters(cfg_path, profile):
        print(f"  tuned filters in {cfg_path.name} from the resume")
    return profile


def _load_profile(cfg: dict, allow_sample: bool,
                  cfg_path: Path | None = None) -> dict | None:
    path = Path(cfg.get("profile_file", "profile.json"))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    resume = _find_resume(cfg)
    if resume is not None:
        if allow_sample:  # --mock stays offline; the real run builds it
            print(f"  ! {path} missing — resume found at {resume.name}, this dry run "
                  f"uses the sample profile; the first real run builds yours.")
        else:
            return _build_profile(resume, path, cfg_path=cfg_path)

    sample = ROOT / "profile.example.json"
    if allow_sample and sample.exists():
        print(f"  ! {path} missing — using {sample.name} for this dry run.")
        print("    Build the real one: drop resume.pdf into the user directory, or")
        print("    python -m jobhunt profile --resume <file> --out <user>/profile.json")
        return json.loads(sample.read_text(encoding="utf-8"))

    print(f"missing {path} — drop a resume (resume.pdf/.docx/.txt/.md) next to the "
          f"user's config.yaml, or run `python -m jobhunt profile --resume <file>` first")
    return None


# ------------------------------------------------------------------ profile --
def cmd_profile(args) -> int:
    if not args.user:
        if not args.resume:
            print("--resume is required (or use --user <name>)")
            return 1
        src = Path(args.resume)
        if not src.exists():
            print(f"resume not found: {src}")
            return 1
        profile = _build_profile(src, Path(args.out or "profile.json"))
        if profile is None:
            return 1
        print(json.dumps(profile, indent=2, ensure_ascii=False)[:900])
        return 0

    u = USERS_DIR / args.user
    if not u.is_dir():
        print(f"no user directory: {u}")
        return 1
    cfg_path = u / "config.yaml"
    cfg = _cfg(cfg_path) if cfg_path.exists() else {}
    out = Path(args.out) if args.out else Path(cfg.get("profile_file", "profile.json"))
    src = Path(args.resume) if args.resume else None

    profile = None
    prev_cwd = os.getcwd()
    try:
        # user-relative paths (resume.*, profile_file) resolve inside user dir
        os.chdir(u)
        if src is None:
            src = _find_resume(cfg)
        if src is None or not src.exists():
            print(f"no resume found in {u} — drop resume.pdf/.docx/.txt/.md there, "
                  f"or pass --resume <file>")
            return 1
        with env_scope(parse_env_file(u / ".env")):
            profile = _build_profile(src, out, cfg_path=cfg_path if cfg_path.exists() else None)
    finally:
        os.chdir(prev_cwd)
    if profile is None:
        return 1
    print(json.dumps(profile, indent=2, ensure_ascii=False)[:900])
    return 0


# ---------------------------------------------------------------------- run --
def cmd_run(args) -> int:
    cfg = _cfg(args.config)
    profile = _load_profile(cfg, allow_sample=args.mock, cfg_path=Path(args.config))
    if profile is None:
        return 1
    store = Store(cfg.get("seen_file", "seen.json"))
    filters = cfg.get("filters", {}) or {}

    # ---- 1. fetch
    print("\n[1/5] fetching boards")
    if args.mock:
        jobs = fetch_all_mock()
    else:
        companies = _cfg(_companies_file(cfg)).get("companies") or []
        if not companies:
            print("companies.yaml has no entries")
            return 1
        jobs = fetch_all(companies)

    # jobs exported by the Indeed scraper (file drop into inbox/)
    inbox_dir = cfg.get("inbox_dir")
    if inbox_dir:
        inbox_jobs = ingest.load_inbox(inbox_dir)
        if inbox_jobs:
            print(f"  inbox: imported {len(inbox_jobs)} job(s) from {inbox_dir}")
        jobs = jobs + inbox_jobs

    scanned = len(jobs)
    if not scanned:
        print("no postings fetched — check the slugs in companies.yaml / the inbox dir")
        return 1

    # ---- 2. prefilter + dedupe (deterministic, free, no LLM)
    print("\n[2/5] filtering")
    jobs = prefilter(jobs, filters)
    passed_filters = len(jobs)
    jobs = store.unseen(jobs)
    print(f"  new since last run: {len(jobs)}")
    candidates = len(jobs)
    if args.limit:
        jobs = jobs[:args.limit]
        print(f"  --limit {args.limit} applied")

    if not jobs:
        subject, doc = digest_mod.build([], scanned, 0, store.stats())
        path = digest_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
        print(f"\nnothing new today. preview: {path}")
        return 0

    # ---- 3. screen
    scorer = "keyword" if args.scorer == "keyword" else "llm"
    if scorer == "keyword":
        print(f"\n[3/5] screening {len(jobs)} jobs (keyword stub — DEV ONLY)")
        llm.keyword_screen(jobs, profile)
    else:
        try:
            provider, model = resolve("screen")
        except LLMError as e:
            print(f"\n{e}\nNo key? Run with --scorer keyword for an offline dry run.")
            return 1
        print(f"\n[3/5] screening {len(jobs)} jobs via {provider.name}/{model}")
        llm.screen(jobs, profile,
                   batch_size=int(cfg.get("screen_batch_size", 8)),
                   jd_chars=int(cfg.get("screen_jd_chars", 1400)),
                   provider=provider, model=model)

    # If every batch failed, the digest would be empty and — worse — we would
    # record these jobs as seen and never show them again. Bail instead.
    if scorer == "llm" and not any(j.score is not None for j in jobs):
        print("\n! screening scored nothing: every batch failed.\n"
              "  Not recording these jobs, so the next run retries them.\n"
              "  Check the warnings above (bad key, rate limit, wrong model id).")
        return 1

    threshold = float(cfg.get("score_threshold", 7.0))
    top_n = int(cfg.get("max_per_digest", 5))
    shortlist = sorted([j for j in jobs if (j.score or 0) >= threshold],
                       key=lambda j: j.score or 0, reverse=True)[:top_n]
    print(f"  {len(shortlist)} scored >= {threshold}")

    # ---- 4. draft
    print(f"\n[4/5] drafting kits for {len(shortlist)}")
    if not shortlist:
        print("  nothing cleared the threshold")
    elif scorer == "keyword" or args.no_draft:
        print("  skipped (keyword scorer / --no-draft)")
    else:
        try:
            provider, model = resolve("draft")
            print(f"  via {provider.name}/{model}")
            llm.draft(shortlist, profile,
                      jd_chars=int(cfg.get("draft_jd_chars", 6000)),
                      provider=provider, model=model)
        except LLMError as e:
            print(f"  ! drafting unavailable: {e}")

    # ---- 5. digest
    print("\n[5/5] digest")
    subject, doc = digest_mod.build(shortlist, scanned, candidates, store.stats())
    path = digest_mod.write(doc, cfg.get("digest_file", "out/digest.html"))
    print(f"  wrote {path}")

    sent = False
    if args.send:
        try:
            mailer.send(subject, doc)
            sent = True
        except Exception as e:  # bad app password, blocked port, offline
            print(f"  ! email failed ({type(e).__name__}: {e}) — digest still on disk")
    else:
        print("  --send not passed, email skipped")

    store.record(jobs, emailed=sent)
    csv_path = store.export_csv(cfg.get("tracker_csv", "out/tracker.csv"))

    print(f"\nfunnel: {scanned} scanned -> {passed_filters} passed filters "
          f"-> {candidates} new -> {len(shortlist)} in digest")
    print(f"subject: {subject}")
    print(f"tracker: {store.stats()}  ({csv_path})")
    return 0


# ---------------------------------------------------------------- run-all --
def _user_dirs(users_dir: Path, only: str | None = None) -> list[Path]:
    """Which user dirs to sweep: everyone except paused ones, or just the
    named one. An explicit `--user` overrides a .paused marker — naming
    someone is asking for them specifically. `sample` is scaffold, not a
    user; it's skipped in a sweep but runs if named outright."""
    if only:
        return [users_dir / only]
    return [d for d in sorted(users_dir.iterdir()) if d.is_dir()
            and d.name != "sample" and not (d / ".paused").exists()]


def cmd_run_all(args) -> int:
    """Run the pipeline for every user in users/*/, sequentially.

    Each user dir holds its own config.yaml + .env; env vars are applied
    scoped (override, then restore) so one user's API key never leaks into
    the next run. One user failing never aborts the sweep.
    """
    if not USERS_DIR.is_dir():
        print(f"no users/ directory at {USERS_DIR} — nothing to run")
        return 1
    users = _user_dirs(USERS_DIR, args.user)
    if args.user is None:
        paused = sorted(d.name for d in USERS_DIR.iterdir()
                        if d.is_dir() and (d / ".paused").exists())
        if paused:
            print(f"paused (skipped): {', '.join(paused)} — "
                  "delete their .paused marker to resume")
    if not users:
        print("no user directories found")
        return 1




    failed: list[str] = []
    for u in users:
        print(f"\n{'=' * 60}\nuser: {u.name}\n{'=' * 60}")
        cfg_path = u / "config.yaml"
        if not cfg_path.exists():
            print(f"  ! {cfg_path} missing — skipped")
            failed.append(u.name)
            continue
        run_args = argparse.Namespace(
            config=str(cfg_path), mock=args.mock, scorer=args.scorer,
            no_draft=args.no_draft, send=args.send, limit=args.limit,
        )
        prev_cwd = os.getcwd()
        try:
            # user config paths are relative to the user dir, not the root
            os.chdir(u)
            with env_scope(parse_env_file(u / ".env")):
                rc = cmd_run(run_args)
        except Exception as e:  # never abort the sweep
            print(f"  ! crashed ({type(e).__name__}: {e}) — continuing")
            rc = 1
        finally:
            os.chdir(prev_cwd)
        if rc != 0:
            failed.append(u.name)
        print(f"\nuser {u.name}: {'FAILED' if rc else 'ok'}")

    print(f"\n{'=' * 60}\nrun-all: {len(users) - len(failed)}/{len(users)} ok"
          + (f", failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


# ------------------------------------------------------------------- misc --
def cmd_ui(args) -> int:
    """Local web UI: review drafts, edit notes, mark applied, start runs;
    upload a resume, build/edit profile.json, edit the user's .env."""
    from .server import serve  # deferred: only the UI needs http.server
    serve(port=args.port, default_user=args.user,
          open_browser=not args.no_open)
    return 0


def cmd_applied(args) -> int:
    store = Store(_cfg(args.config).get("seen_file", "seen.json"))
    ok = store.mark_applied(args.job_id)
    print("marked applied" if ok else f"unknown job_id: {args.job_id}")
    return 0 if ok else 1


def cmd_stats(args) -> int:
    cfg = _cfg(args.config)
    store = Store(cfg.get("seen_file", "seen.json"))
    print(json.dumps(store.stats(), indent=2))
    print(f"csv: {store.export_csv(cfg.get('tracker_csv', 'out/tracker.csv'))}")
    return 0


def main(argv=None) -> int:
    _load_env()
    p = argparse.ArgumentParser(
        prog="jobhunt",
        description="Personal job-search agent. Finds and drafts; never submits.")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("profile", help="turn a resume into profile.json")
    sp.add_argument("--resume", help="path to a .pdf, .docx, .txt or .md resume")
    sp.add_argument("--out", help="output path (default: profile.json, or the "
                                  "user's configured profile_file with --user)")
    sp.add_argument("--user", help="build for this user under users/: their .env "
                                   "key, their resume.*, their profile.json")
    sp.set_defaults(func=cmd_profile)

    sr = sub.add_parser("run", help="run the daily pipeline")
    sr.add_argument("--mock", action="store_true", help="bundled fixtures, no network")
    sr.add_argument("--scorer", choices=["llm", "keyword", "claude"], default="llm",
                    help="keyword = offline stub, needs no API key ('claude' is an "
                         "alias for 'llm', kept for older docs)")
    sr.add_argument("--no-draft", action="store_true", help="skip the expensive stage")
    sr.add_argument("--send", action="store_true", help="actually email the digest")
    sr.add_argument("--limit", type=int, help="cap jobs sent to the LLM (cost guard)")
    sr.set_defaults(func=cmd_run)

    ra = sub.add_parser("run-all", help="run the pipeline for every user in users/")
    ra.add_argument("--mock", action="store_true", help="bundled fixtures, no network")
    ra.add_argument("--scorer", choices=["llm", "keyword", "claude"], default="llm",
                    help="keyword = offline stub, needs no API key")
    ra.add_argument("--no-draft", action="store_true", help="skip the expensive stage")
    ra.add_argument("--send", action="store_true", help="actually email the digest")
    ra.add_argument("--limit", type=int, help="cap jobs sent to the LLM (cost guard)")
    ra.add_argument("--user", help="run only this user (directory name under users/)")
    ra.set_defaults(func=cmd_run_all)

    su = sub.add_parser("ui", help="local web UI: review drafts, mark applied")
    su.add_argument("--port", type=int, default=8765)
    su.add_argument("--user", help="open with this user preselected")
    su.add_argument("--no-open", action="store_true",
                    help="don't auto-open the browser")
    su.set_defaults(func=cmd_ui)

    sa = sub.add_parser("applied", help="mark a job_id as applied")
    sa.add_argument("job_id")
    sa.set_defaults(func=cmd_applied)

    ss = sub.add_parser("stats", help="tracker summary + CSV export")
    ss.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
