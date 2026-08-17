"""Parsers + prefilter, run against the fixtures in their native ATS shapes.

No network, no API key. This is the suite that catches the two bugs that cost
me an evening each: Lever's epoch-milliseconds timestamps, and a bare `sde`
regex that silently matches nothing.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt import mock
from jobhunt.fetch import (fetch_smartrecruiters, parse_ashby, parse_greenhouse,
                           parse_lever, parse_smartrecruiters, strip_html)
from jobhunt.mock import fetch_all_mock
from jobhunt.prefilter import prefilter

CONFIG = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml")
                        .read_text(encoding="utf-8"))
FILTERS = CONFIG["filters"]


# ------------------------------------------------------------- strip_html ---

def test_strip_html_unescapes_twice():
    """Greenhouse ships HTML-entity-escaped HTML: unescape, strip, unescape."""
    raw = "&lt;p&gt;Go &amp;amp; Java&lt;/p&gt;"
    assert strip_html(raw) == "Go & Java"


def test_strip_html_turns_block_tags_into_newlines():
    out = strip_html("<p>One</p><p>Two</p><ul><li>a</li><li>b</li></ul>")
    assert "One" in out and "Two" in out and "a" in out and "b" in out
    assert "<" not in out


def test_strip_html_handles_none_and_empty():
    assert strip_html(None) == ""
    assert strip_html("") == ""


# ---------------------------------------------------------------- parsers ---

def test_greenhouse_maps_every_field():
    jobs = parse_greenhouse("acme-edge", "Acme Edge", mock.GREENHOUSE["acme-edge"])
    j = next(j for j in jobs if j.title.startswith("Software Engineer II"))
    assert j.job_id == "greenhouse:acme-edge:5501001"
    assert j.ats == "greenhouse"
    assert j.company == "Acme Edge"
    assert j.location == "Bangalore, India"
    assert j.url.startswith("https://boards.greenhouse.io/")
    assert "distributed services" in j.description


def test_lever_concatenates_description_lists_and_additional():
    """The requirements live in lists[], not descriptionPlain. Drop the
    concatenation and every Lever job looks unqualified."""
    jobs = parse_lever("quantstack", "QuantStack", mock.LEVER["quantstack"])
    j = next(j for j in jobs if j.title == "Backend Engineer (Go)")
    assert "market data pipeline" in j.description      # descriptionPlain
    assert "Requirements" in j.description              # lists[].text
    assert "2-5 years backend experience" in j.description  # lists[].content
    assert "No take-home" in j.description              # additionalPlain


def test_lever_createdAt_is_epoch_milliseconds():
    """1.7e12 is milliseconds. Reading it as seconds dates the post to 1970
    and the freshness filter eats the whole board without a word."""
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    jobs = parse_lever("quantstack", "QuantStack", mock.LEVER["quantstack"])
    j = next(j for j in jobs if j.title == "Backend Engineer (Go)")
    assert j.posted_at == two_days_ago.isoformat()


def test_ashby_skips_unlisted_drafts():
    jobs = parse_ashby("helioscale", "Helioscale", mock.ASHBY["helioscale"])
    assert all("unlisted" not in j.url for j in jobs)
    assert len(jobs) == 2   # 3 postings, one isListed: false


def test_ashby_reads_compensation_and_html_fallback():
    jobs = parse_ashby("helioscale", "Helioscale", mock.ASHBY["helioscale"])
    networking = next(j for j in jobs if j.title == "Software Engineer, Networking")
    assert networking.salary == "₹32L – ₹48L"
    ds = next(j for j in jobs if j.title == "Data Scientist, Growth")
    assert "Causal inference" in ds.description   # descriptionHtml fallback


def test_job_ids_are_globally_unique_and_namespaced():
    jobs = fetch_all_mock()
    ids = [j.job_id for j in jobs]
    assert len(ids) == len(set(ids))
    assert all(re.match(r"^(greenhouse|lever|ashby):[^:]+:.+$", i) for i in ids)


def test_parsers_take_decoded_json_not_a_response():
    """Parsers are pure: body in, list[Job] out. That is what makes --mock
    exercise the real code path instead of a second implementation."""
    assert parse_greenhouse("x", "X", {}) == []
    assert parse_lever("x", "X", []) == []
    assert parse_ashby("x", "X", {}) == []
    assert parse_smartrecruiters("x", "X", {}) == []


SR_PAGE_1 = {
    "totalFound": 3, "content": [
        {"id": "a1", "name": "Software Engineer, Backend",
         "location": {"city": "Noida", "region": "UP", "country": "in",
                      "fullLocation": "Noida, , India"},
         "ref": "https://api.smartrecruiters.com/v1/companies/X/postings/a1",
         "releasedDate": "2026-08-01T00:00:00.000Z"},
        {"id": "a2", "name": "Sales Director",
         "location": {"city": "London", "country": "uk"},
         "releasedDate": "2026-08-02T00:00:00.000Z"},
    ]}
SR_PAGE_2 = {
    "totalFound": 3, "content": [
        {"id": "a3", "name": "Platform Engineer",
         "location": {"city": "Remote"},
         "releasedDate": "2026-08-03T00:00:00.000Z"},
    ]}
SR_DETAIL = {
    "jobAd": {"sections": {
        "jobDescription": {"text": "<p>Build <b>Go</b> services.</p>"},
        "qualifications": {"text": "<p>3+ years Go.</p>"},
        "companyDescription": {"text": "ignored noise"},
        "additionalInformation": {"text": ""},
    }}}


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _FakeSession:
    """Replays canned responses in order; records the URLs it was asked for."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.responses.pop(0)


def test_parse_smartrecruiters_maps_fields():
    jobs = parse_smartrecruiters("Experian", "Experian", SR_PAGE_1)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.job_id == "smartrecruiters:Experian:a1"
    assert j.location == "Noida, India"
    assert j.url == "https://jobs.smartrecruiters.com/Experian/a1"
    assert j.posted_at.startswith("2026-08-01")
    # no fullLocation -> city/region/country joined, blanks dropped
    assert jobs[1].location == "London, uk"


def test_fetch_smartrecruiters_pages_and_fills_descriptions():
    sess = _FakeSession([
        _Resp(200, SR_PAGE_1), _Resp(200, SR_PAGE_2),
        _Resp(200, SR_DETAIL),          # a1: engineer title -> detail fetched
        _Resp(200, SR_DETAIL),          # a3: "Platform Engineer" also matches
    ])
    jobs = fetch_smartrecruiters("Experian", "Experian", sess)
    assert [j.job_id.rsplit(":", 1)[-1] for j in jobs] == ["a1", "a2", "a3"]
    assert "Build Go services." in jobs[0].description
    assert "3+ years Go." in jobs[0].description
    assert "ignored noise" not in jobs[0].description
    # detail pass skips non-engineering titles (a2 = Sales Director)
    detail_urls = [u for u in sess.urls if u.endswith(("/a1", "/a2", "/a3"))]
    assert detail_urls == [
        "https://api.smartrecruiters.com/v1/companies/Experian/postings/a1",
        "https://api.smartrecruiters.com/v1/companies/Experian/postings/a3"]


# -------------------------------------------------------------- prefilter ---

@pytest.mark.parametrize("title", [
    "Software Engineer II, Distributed Systems",
    "Software Development Engineer, Core Infra",
    "Backend Engineer (Go)",
    "Site Reliability Engineer",
    "SDE II",
])
def test_include_titles_match_real_titles(title):
    inc = FILTERS["include_titles"]
    assert any(re.search(p, title, re.I) for p in inc), title


def test_bare_sde_regex_does_not_match_the_spelled_out_title():
    """The bug: `sde` looks like it covers "Software Development Engineer".
    It does not — they share no substring. \\bsde\\b plus the spelled-out
    variant is why both titles survive the filter."""
    assert not re.search(r"\bsde\b", "Software Development Engineer", re.I)
    assert re.search(r"\bsde\b", "SDE II", re.I)
    inc = FILTERS["include_titles"]
    assert any(re.search(p, "Software Development Engineer, Core Infra", re.I) for p in inc)


@pytest.mark.parametrize("title", [
    "Staff Software Engineer, Storage",       # too senior
    "Engineering Manager, Platform",          # management track
    "Enterprise Account Executive",           # wrong function
    "Frontend Engineer, Design Systems",      # wrong discipline
    "Data Scientist, Growth",                 # wrong discipline
])
def test_junk_titles_are_rejected(title):
    inc, exc = FILTERS["include_titles"], FILTERS["exclude_titles"]
    included = any(re.search(p, title, re.I) for p in inc)
    excluded = any(re.search(p, title, re.I) for p in exc)
    assert excluded or not included, f"{title!r} would have survived"


def test_full_mock_funnel_keeps_only_the_five_real_matches():
    # The mock board mixes "Bangalore, India" and bare "Bangalore" locations;
    # pin the city list so tuning `locations` in config.yaml (dropping
    # bangalore, adding pune...) does not silently redefine this test.
    cfg = dict(FILTERS, locations=list(FILTERS["locations"]) + ["bangalore", "bengaluru"])
    kept = prefilter(fetch_all_mock(), cfg)
    titles = sorted(j.title for j in kept)
    assert titles == [
        "Backend Engineer (Go)",
        "Site Reliability Engineer",
        "Software Development Engineer, Core Infra",
        "Software Engineer II, Distributed Systems",
        "Software Engineer, Networking",
    ]


def test_stale_posting_is_dropped_by_freshness_gate():
    kept = prefilter(fetch_all_mock(), FILTERS)
    assert not any("Senior Software Engineer, Platform" == j.title for j in kept)


def test_wrong_city_dropped_but_remote_kept():
    cfg = dict(FILTERS, locations=list(FILTERS["locations"]) + ["bangalore", "bengaluru"])
    kept = prefilter(fetch_all_mock(), cfg)
    assert not any("San Francisco" in (j.location or "") for j in kept)
    assert any("Remote" in (j.location or "") for j in kept)


def test_allow_remote_is_what_lets_an_out_of_region_remote_role_through():
    """"Remote (India)" already matches the `india` location, so it is the
    wrong fixture for this. Use a remote role that names no allowed city."""
    from jobhunt.fetch import Job
    remote = Job(job_id="lever:x:1", ats="lever", company="X",
                 title="Backend Engineer", location="Remote - Global",
                 url="https://example.com", description="Go")

    kept_on = prefilter([remote], dict(FILTERS, allow_remote=True))
    kept_off = prefilter([remote], dict(FILTERS, allow_remote=False))

    assert len(kept_on) == 1
    assert kept_off == []


def _job(title: str, location: str) -> "Job":
    from jobhunt.fetch import Job
    return Job(job_id=f"x:{title}:{location}", ats="greenhouse", company="X",
               title=title, location=location, url="https://example.com",
               description="")


def test_distributed_in_the_title_is_not_a_remote_claim():
    """The leak that filled the digest with on-site US/EU jobs: "distributed"
    sat in REMOTE_HINTS and hints were matched against location+title, so
    every "Distributed Systems Engineer" anywhere on earth passed the gate."""
    kept = prefilter(
        [_job("Software Engineer II, Distributed Systems", "Portland, Oregon, USA")],
        FILTERS)
    assert kept == []


def test_india_does_not_match_indiana_or_indianapolis():
    kept = prefilter(
        [_job("Software Engineer", "Indianapolis, Indiana")],
        FILTERS)
    assert kept == []


def test_exclude_locations_kills_geo_restricted_remote():
    cfg = dict(FILTERS, exclude_locations=[r"\b(united states|emea)\b"])
    assert prefilter([_job("Backend Engineer", "Remote, United States")], cfg) == []
    assert prefilter([_job("Backend Engineer", "Remote (EMEA)")], cfg) == []
    # but a plain global remote with no named region still passes
    assert len(prefilter([_job("Backend Engineer", "Remote")], cfg)) == 1
    # and a wanted location still works when nothing is excluded
    assert len(prefilter([_job("Backend Engineer", "Noida, India")], cfg)) == 1


def test_empty_filters_keep_everything():
    jobs = fetch_all_mock()
    assert len(prefilter(jobs, {})) == len(jobs)
