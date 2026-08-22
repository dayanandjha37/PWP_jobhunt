"""Store dedupe + requeue semantics: a job comes back until delivered.

The `emailed` flag is the delivery receipt. unseen() requeues anything
without one, and record() upserts so a retried job keeps its history and
never un-delivers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.fetch import Job
from jobhunt.store import Store


def _job(job_id: str = "greenhouse:acme:1", **over) -> Job:
    kw = dict(job_id=job_id, ats="greenhouse", company="Acme",
              title="Recruiter", location="Delhi", url="https://acme.example/j",
              description="jd")
    kw.update(over)
    return Job(**kw)


def test_unseen_requeues_never_emailed(tmp_path):
    store = Store(tmp_path / "seen.json")
    store.record([_job()], emailed=False)

    again = store.unseen([_job()])

    assert [j.job_id for j in again] == ["greenhouse:acme:1"]


def test_unseen_does_not_requeue_emailed(tmp_path):
    store = Store(tmp_path / "seen.json")
    store.record([_job("greenhouse:acme:1")], emailed=True)
    store.record([_job("greenhouse:acme:2")], emailed=False)

    again = store.unseen([_job("greenhouse:acme:1"), _job("greenhouse:acme:2"),
                          _job("greenhouse:acme:3")])

    assert [j.job_id for j in again] == ["greenhouse:acme:2", "greenhouse:acme:3"]


def test_record_flips_emailed_false_to_true(tmp_path):
    store = Store(tmp_path / "seen.json")
    store.record([_job()], emailed=False)

    store.record([_job()], emailed=True)  # the retry delivered

    assert Store(tmp_path / "seen.json").data["greenhouse:acme:1"]["emailed"] is True


def test_record_true_stays_true_across_failed_resend(tmp_path):
    """A later run that fails to send must not un-deliver a delivered job."""
    store = Store(tmp_path / "seen.json")
    store.record([_job()], emailed=True)

    store.record([_job()], emailed=False)

    assert store.data["greenhouse:acme:1"]["emailed"] is True


def test_rerecord_preserves_first_seen_and_applied(tmp_path):
    store = Store(tmp_path / "seen.json")
    store.record([_job(score=6.0)], emailed=True)
    first_seen = store.data["greenhouse:acme:1"]["first_seen"]
    store.mark_applied("greenhouse:acme:1")

    store.record([_job(score=8.5, reason="strong overlap",
                       draft={"cover_note": "hi"})], emailed=True)

    row = store.data["greenhouse:acme:1"]
    assert row["first_seen"] == first_seen
    assert row["applied"] is True and row["applied_on"] is not None
    # the rerun refreshes what it produced
    assert row["score"] == 8.5
    assert row["reason"] == "strong overlap"
    assert row["draft"]["cover_note"] == "hi"


def test_rerecord_keeps_old_score_when_rerun_scored_nothing(tmp_path):
    """A keyword/failed screen leaves score None — don't wipe the last one."""
    store = Store(tmp_path / "seen.json")
    store.record([_job(score=7.5, reason="good")], emailed=False)

    store.record([_job(score=None, reason=None, draft={})], emailed=False)

    row = store.data["greenhouse:acme:1"]
    assert row["score"] == 7.5 and row["reason"] == "good"


def test_stats_counts(tmp_path):
    store = Store(tmp_path / "seen.json")
    store.record([_job("greenhouse:acme:1"), _job("greenhouse:acme:2"),
                  _job("greenhouse:acme:3")], emailed=True)
    store.record([_job("greenhouse:acme:4")], emailed=False)
    store.mark_applied("greenhouse:acme:2")

    assert store.stats() == {"tracked": 4, "emailed": 3, "applied": 1}
