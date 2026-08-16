"""Ingest jobs exported by the Indeed scraper (NaukriResumeUploader).

Handoff is a file drop: one JSON per job into a user's inbox/ directory.
Expected shape (written by JobExportService on the Java side):

    {"job_id": "<indeed jk>", "source": "indeed", "title": ...,
     "company": ..., "location": ..., "url": ...,
     "description": ..., "fetched_at": "2026-08-15T09:00:00+05:30"}

Parsed files move to inbox/archive/, malformed ones to inbox/failed/ — a bad
file must never crash the run, and a consumed file must never be read twice.
Dedupe needs no extra work: seen.json is keyed on job_id and the mapped id
"indeed:indeed:<jk>" is namespaced like the ATS ids.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .fetch import Job


def _jk_from(data: dict) -> str:
    """Accept "<jk>", "indeed:<jk>" or "indeed:indeed:<jk>" in job_id."""
    jk = str(data.get("job_id") or data.get("jk") or "")
    for _ in range(2):
        if jk.startswith("indeed:"):
            jk = jk[len("indeed:"):]
    return jk.strip()


def _move(src: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():  # same jk exported twice: latest wins
        dest.unlink()
    shutil.move(str(src), str(dest))


def load_inbox(inbox_dir: str | Path) -> list[Job]:
    """Read inbox/*.json into Jobs, archiving what was consumed.
    Malformed files go to inbox/failed/. Never raises."""
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return []
    jobs: list[Job] = []
    for f in sorted(inbox.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"expected object, got {type(data).__name__}")
            jk = _jk_from(data)
            if not jk:
                raise ValueError("no job_id/jk field")
            title = str(data.get("title") or "").strip()
            if not title:
                raise ValueError("no title")
            jobs.append(Job(
                job_id=f"indeed:indeed:{jk}",
                ats="indeed",
                company=str(data.get("company") or "Unknown").strip(),
                title=title,
                location=str(data.get("location") or "").strip(),
                url=str(data.get("url") or ""),
                description=str(data.get("description") or "").strip(),
                posted_at=data.get("fetched_at"),
            ))
            _move(f, inbox / "archive")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"  ! inbox: {f.name} unreadable ({e}) — moved to failed/")
            _move(f, inbox / "failed")
    return jobs
