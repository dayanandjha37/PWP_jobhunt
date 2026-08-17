"""Deterministic filter that runs BEFORE any LLM call.

This is the whole cost story: ~2000 raw jobs -> ~40 candidates for ~0 rupees,
so Claude only ever reads jobs that already passed title + location + freshness.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .fetch import Job

# Matched against the LOCATION string only, never the title — a title like
# "Distributed Systems Engineer" is not a remote claim, and matching it there
# lets every on-site distributed-systems job in the world through the gate.
REMOTE_HINTS = ("remote", "anywhere", "work from home", "wfh", "distributed")
REMOTE_PAT = re.compile("|".join(rf"\b{re.escape(h)}\b" for h in REMOTE_HINTS), re.I)


def _word_pats(needles: list[str]) -> list[re.Pattern]:
    """Whole-word matching. Substring matching made "india" match "Indiana"
    and "Indianapolis" — word boundaries kill that whole class of false hit."""
    return [re.compile(rf"\b{re.escape(n)}\b", re.I) for n in needles]


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(v) if fmt is None else datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def prefilter(jobs: list[Job], cfg: dict) -> list[Job]:
    inc = cfg.get("include_titles") or [r"."]
    exc = cfg.get("exclude_titles") or []
    loc_pats = _word_pats([l.lower() for l in (cfg.get("locations") or [])])
    excl_locs = [re.compile(p, re.I) for p in (cfg.get("exclude_locations") or [])]
    allow_remote = bool(cfg.get("allow_remote", True))
    max_age = cfg.get("max_age_days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age) if max_age else None

    kept, stats = [], {"title": 0, "location": 0, "age": 0}
    for j in jobs:
        if not _any_match(inc, j.title) or (exc and _any_match(exc, j.title)):
            stats["title"] += 1
            continue

        if loc_pats or excl_locs:
            loc = j.location or ""
            # exclude_locations wins even over a wanted location: it is what
            # kills "Remote, United States" style geo-restricted remote roles.
            if any(p.search(loc) for p in excl_locs):
                stats["location"] += 1
                continue
            hay = f"{loc} {j.title}"
            is_remote = allow_remote and bool(REMOTE_PAT.search(loc))
            if not is_remote and not any(p.search(hay) for p in loc_pats):
                stats["location"] += 1
                continue

        if cutoff:
            posted = _parse_date(j.posted_at)
            if posted and posted < cutoff:
                stats["age"] += 1
                continue

        kept.append(j)

    print(f"  prefilter: {len(jobs)} -> {len(kept)} "
          f"(dropped title={stats['title']} location={stats['location']} stale={stats['age']})")
    return kept
