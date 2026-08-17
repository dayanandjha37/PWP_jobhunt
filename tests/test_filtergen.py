"""filtergen: profile.json -> dynamic config.yaml filters.

derive_filters is deterministic (no LLM at tune time — the resume already
went through one); sync_filters is text surgery so thresholds, paths and
comments in the user's config.yaml survive a retune."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.filtergen import derive_filters, sync_filters


def _profile(**kw):
    base = {
        "name": "X", "current_title": "Software Engineer", "years_experience": 3,
        "target_titles": ["Backend Engineer", "Software Development Engineer"],
        "seniority": "mid",
    }
    base.update(kw)
    return base


# ------------------------------------------------------------------ derive --

def test_derive_builds_include_patterns_from_target_titles():
    d = derive_filters(_profile())
    assert r"\bbackend[\s/\-]+engineer\b" in d["include_titles"]
    # phrase target also admits its acronym
    assert r"\bsde\b" in d["include_titles"]


def test_derive_strips_level_suffixes():
    d = derive_filters(_profile(target_titles=["Backend Engineer II"],
                                current_title=""))
    assert d["include_titles"] == [r"\bbackend[\s/\-]+engineer\b"]


def test_derive_junior_excludes_senior_staff_senior_does_not():
    junior = derive_filters(_profile(seniority="junior"))
    assert any("senior" in p for p in junior["exclude_titles"])
    senior = derive_filters(_profile(seniority="senior", years_experience=8))
    assert not any(r"\bsenior\b" in p or "(senior|" in p
                   for p in senior["exclude_titles"])
    # leadership stays excluded at every tier
    assert any("manager" in p for p in senior["exclude_titles"])


def test_derive_falls_back_to_years_when_seniority_missing():
    by_years = derive_filters(_profile(seniority="", years_experience=1))
    assert any("senior" in p for p in by_years["exclude_titles"])


def test_derive_intern_keeps_internships_everyone_else_drops_them():
    intern = derive_filters(_profile(seniority="intern"))["exclude_titles"]
    mid = derive_filters(_profile(seniority="mid"))["exclude_titles"]
    assert not any("intern" in p for p in intern)
    assert any("intern" in p for p in mid)


def test_derive_locations_passed_through_lowercased():
    d = derive_filters(_profile(locations=["Noida", " Delhi NCR ", ""]))
    assert d["locations"] == ["noida", "delhi ncr"]


def test_derive_without_locations_omits_the_key():
    assert "locations" not in derive_filters(_profile())


def test_derive_without_titles_keeps_a_broad_gate():
    d = derive_filters({"years_experience": 5})
    assert d["include_titles"] and d["exclude_titles"]


def test_derive_non_tech_profile_skips_wrong_discipline_excludes():
    tech = derive_filters(_profile())
    notech = derive_filters(_profile(target_titles=["Product Manager"],
                                     current_title="Product Manager"))
    assert any("sales" in p for p in tech["exclude_titles"])
    assert not any("sales" in p for p in notech["exclude_titles"])


# ------------------------------------------------------------------- sync --

CFG = """\
# top comment survives
filters:
  include_titles:
    - '\\bjava\\b.*\\bdeveloper\\b'
  exclude_titles:
    - '\\b(staff|principal)\\b'
  locations:
    - bangalore
  allow_remote: true      # keep me
  max_age_days: 30
score_threshold: 7.0
companies_file: companies.yaml
"""


def test_sync_rewrites_only_the_dynamic_lists(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CFG, encoding="utf-8")
    assert sync_filters(p, _profile(seniority="junior", locations=["Pune"]))
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    f = cfg["filters"]
    assert r"\bbackend[\s/\-]+engineer\b" in f["include_titles"]
    assert f["locations"] == ["pune"]
    # untouched neighbours
    assert f["allow_remote"] is True and f["max_age_days"] == 30
    assert cfg["score_threshold"] == 7.0 and cfg["companies_file"] == "companies.yaml"
    text = p.read_text(encoding="utf-8")
    assert "# top comment survives" in text and "# keep me" in text


def test_sync_without_profile_locations_keeps_config_locations(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(CFG, encoding="utf-8")
    sync_filters(p, _profile())  # no locations in profile
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["filters"]["locations"] \
        == ["bangalore"]


def test_sync_appends_filters_block_when_missing(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("score_threshold: 6.0\n", encoding="utf-8")
    assert sync_filters(p, _profile(locations=["Chennai"]))
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["score_threshold"] == 6.0
    assert cfg["filters"]["locations"] == ["chennai"]


def test_sync_missing_config_returns_false(tmp_path):
    assert sync_filters(tmp_path / "nope.yaml", _profile()) is False


def test_sync_roundtrips_through_the_real_scaffold(tmp_path):
    """The repo's own sample config must stay parseable after a retune."""
    p = tmp_path / "config.yaml"
    p.write_text((Path(__file__).resolve().parent.parent
                  / "users/sample/config.yaml").read_text(encoding="utf-8"),
                 encoding="utf-8")
    sync_filters(p, _profile(seniority="new-grad", locations=["Noida"]))
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert cfg["filters"]["locations"] == ["noida"]
    assert cfg["inbox_dir"] == "inbox"
