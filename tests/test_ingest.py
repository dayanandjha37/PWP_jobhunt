"""Ingest of the Indeed export (file drop from NaukriResumeUploader).

Fixtures are in the exact shape JobExportService writes. What matters:
the job_id namespacing (dedupe rides on seen.json), the archive move
(consume-once), and that a malformed file never kills the run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.ingest import load_inbox

TWO_DAYS_AGO = (datetime.now(timezone.utc) - timedelta(days=2)
                ).isoformat(timespec="seconds")


def export(**over) -> dict:
    """One job in the JobExportService shape."""
    doc = {
        "job_id": "a1b2c3d4",
        "source": "indeed",
        "title": "Backend Engineer, Java",
        "company": "Acme",
        "location": "Bengaluru, Karnataka",
        "url": "https://in.indeed.com/viewjob?jk=a1b2c3d4",
        "description": "Spring Boot microservices. 2+ years Java.",
        "fetched_at": TWO_DAYS_AGO,
    }
    doc.update(over)
    return doc


def write(inbox: Path, name: str, doc) -> Path:
    p = inbox / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc),
                 encoding="utf-8")
    return p


def test_maps_export_fields_onto_job(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write(inbox, "indeed-a1b2c3d4.json", export())

    jobs = load_inbox(inbox)

    assert len(jobs) == 1
    j = jobs[0]
    assert j.job_id == "indeed:indeed:a1b2c3d4"
    assert j.ats == "indeed"
    assert j.company == "Acme"
    assert j.title == "Backend Engineer, Java"
    assert j.location == "Bengaluru, Karnataka"
    assert j.url.endswith("jk=a1b2c3d4")
    assert "Spring Boot" in j.description
    assert j.posted_at == TWO_DAYS_AGO


def test_job_id_accepts_already_namespaced_forms(tmp_path):
    """The Java side may write "<jk>", "indeed:<jk>" or the full mapped id.
    All must land on the same dedupe key."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write(inbox, "a.json", export(job_id="indeed:a1b2c3d4"))
    write(inbox, "b.json", export(job_id="indeed:indeed:a1b2c3d4"))

    jobs = load_inbox(inbox)
    assert [j.job_id for j in jobs] == ["indeed:indeed:a1b2c3d4"] * 2


def test_consumed_files_move_to_archive(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write(inbox, "indeed-a1b2c3d4.json", export())

    load_inbox(inbox)

    assert not (inbox / "indeed-a1b2c3d4.json").exists()
    archived = inbox / "archive" / "indeed-a1b2c3d4.json"
    assert archived.exists()
    # second pass reads nothing: consume-once without touching seen.json
    assert load_inbox(inbox) == []


def test_malformed_files_move_to_failed_and_never_crash(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write(inbox, "broken.json", "{not json at all")
    write(inbox, "list.json", "[1, 2, 3]")
    write(inbox, "no-title.json", {"job_id": "x", "description": "d"})
    write(inbox, "no-id.json", {"title": "t", "description": "d"})
    write(inbox, "good.json", export())

    jobs = load_inbox(inbox)

    assert [j.job_id for j in jobs] == ["indeed:indeed:a1b2c3d4"]
    failed = sorted(p.name for p in (inbox / "failed").glob("*.json"))
    assert failed == ["broken.json", "list.json", "no-id.json", "no-title.json"]
    assert not (inbox / "good.json").exists()


def test_missing_or_empty_inbox_returns_empty(tmp_path):
    assert load_inbox(tmp_path / "nope") == []
    (tmp_path / "empty").mkdir()
    assert load_inbox(tmp_path / "empty") == []


def test_ingested_jobs_dedupe_via_seen_store(tmp_path):
    """The whole point of the id format: seen.json works unmodified.
    Simulate a re-export of the same job after it was recorded as seen."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    write(inbox, "indeed-a1b2c3d4.json", export())

    from jobhunt.store import Store
    store = Store(tmp_path / "seen.json")
    store.record(store.unseen(load_inbox(inbox)), emailed=False)

    archived = inbox / "archive" / "indeed-a1b2c3d4.json"
    (inbox / "indeed-a1b2c3d4.json").write_text(
        archived.read_text(encoding="utf-8"), encoding="utf-8")
    assert store.unseen(load_inbox(inbox)) == []
