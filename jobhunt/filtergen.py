"""Derive config.yaml filters from a built profile.json.

The scaffold config ships software-developer defaults; a QA engineer or a
data analyst should not have to hand-rewrite the title regexes to match
their resume. After a profile build we regenerate the three dynamic lists
(include_titles, exclude_titles, locations) in place — everything else in
config.yaml (thresholds, paths, comments, exclude_locations) survives
byte-identical, and hand edits afterwards stick until the next rebuild.
"""
from __future__ import annotations

import re
from pathlib import Path

# ------------------------------------------------------------ derivation --

# seniority bucket -> titles too senior for that bucket (0 = most junior).
# Buckets come from profile.seniority, falling back to years_experience.
_TOO_SENIOR: dict[int, list[str]] = {
    0: [r"\b(senior|staff|principal|architect|distinguished|fellow|lead)\b"],
    1: [r"\b(staff|principal|architect|distinguished|fellow)\b"],
    2: [r"\b(principal|distinguished|fellow)\b"],
    3: [],
}
_LEADERSHIP = r"\b(manager|management|director|vp|vice president|head of|chief|cto)\b"
_INTERN = r"\b(intern|internship|apprentice|trainee)\b"
_WRONG_DISCIPLINE = r"\b(sales|account executive|marketing|recruit|support|success)\b"
_TECH_TITLE = re.compile(
    r"engineer|developer|sde|programmer|analyst|scientist|designer"
    r"|qa|tester|devops|sre|architect", re.I)

# Target-title phrases whose acronym is a different token stream: "Software
# Development Engineer" in a target title should also let plain "SDE" through.
_PHRASE_ACRONYMS = {
    "software development engineer": r"\bsde\b",
    "site reliability engineer": r"\bsre\b",
    "member of technical staff": r"\bmts\b",
}

# Trailing tokens that pin a level, not a role — "Backend Engineer II" must
# match every "Backend Engineer" posting, not just the II ones.
_LEVEL_TOKEN = re.compile(r"^(i{1,3}|iv|v|vi+|[0-9]{1,2}|l[0-9]|junior|senior"
                          r"|staff|lead|principal|intern)$", re.I)


def _seniority_tier(profile: dict) -> int:
    s = str(profile.get("seniority") or "").strip().lower()
    if s in ("intern", "new-grad", "new grad", "graduate", "junior", "entry"):
        return 0
    if s in ("mid", "mid-level", "intermediate"):
        return 1
    if s == "senior":
        return 2
    if s in ("staff", "principal", "distinguished", "fellow", "lead"):
        return 3
    try:
        years = float(profile.get("years_experience") or 0)
    except (TypeError, ValueError):
        years = 0.0
    if years < 3:
        return 0
    if years < 6:
        return 1
    if years < 10:
        return 2
    return 3


def _title_pattern(title: str) -> str | None:
    """'Backend Engineer II' -> r'\\bbackend[\\s/\\-]+engineer\\b'. Words must
    appear in order (that is how titles read); matching is case-insensitive."""
    words = [w.lower() for w in re.split(r"[\s/]+", title.strip()) if w]
    while words and _LEVEL_TOKEN.match(words[-1]):
        words.pop()
    if not words:
        return None
    joined = r"[\s/\-]+".join(re.escape(w) for w in words)
    return rf"\b{joined}\b"


def derive_filters(profile: dict) -> dict:
    """profile.json -> the three dynamic filter lists for config.yaml.

    Returns only the keys we can derive; locations is omitted (and the
    config's own list left alone) when the profile carries none.
    """
    titles: list[str] = []
    raw = list(profile.get("target_titles") or []) + [profile.get("current_title") or ""]
    for t in raw:
        t = str(t).strip()
        if t and t.lower() not in {x.lower() for x in titles}:
            titles.append(t)

    includes: list[str] = []
    for t in titles[:12]:
        pat = _title_pattern(t)
        if pat and pat not in includes:
            includes.append(pat)
        low = t.lower()
        for phrase, acro in _PHRASE_ACRONYMS.items():
            if phrase in low and acro not in includes:
                includes.append(acro)
    if not includes:  # no titles extracted — keep the gate broad, not empty
        includes = [r"\b(engineer|developer|analyst|scientist|manager)\b"]

    excludes = [_LEADERSHIP, *_TOO_SENIOR[_seniority_tier(profile)]]
    if str(profile.get("seniority") or "").strip().lower() != "intern":
        excludes.append(_INTERN)
    if _TECH_TITLE.search(" ".join(titles)):
        excludes.append(_WRONG_DISCIPLINE)

    out = {"include_titles": includes, "exclude_titles": excludes}
    locs = profile.get("locations")
    if isinstance(locs, list):
        clean = [str(l).strip().lower() for l in locs if str(l).strip()]
        if clean:
            out["locations"] = clean
    return out


# --------------------------------------------------------------- rewriting --

_LIST_KEYS = ("include_titles", "exclude_titles", "locations")
_TOP_KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:")
_KEY_LINE = re.compile(r"^(\s*)([\w-]+)\s*:")
_ITEM_LINE = re.compile(r"^\s+-\s")
_NOTE = ("# regenerated from the resume by `python -m jobhunt profile` — "
         "hand edits welcome, next rebuild overwrites")


def _quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _render_list(key: str, items: list[str], indent: str,
                 note: bool = False) -> list[str]:
    out = [f"{indent}{_NOTE}"] if note else []
    out.append(f"{indent}{key}:")
    out += [f"{indent}  - {_quote(s)}" for s in items]
    return out


def _splice(block: list[str], key: str, items: list[str]) -> list[str]:
    """Replace `key:`'s list inside the filters block (list items + indented
    comments below it go too); append the key at block end when absent."""
    for i, line in enumerate(block):
        m = _KEY_LINE.match(line)
        if not m or m.group(2) != key:
            continue
        indent = m.group(1)
        j = i + 1
        while j < len(block) and (_ITEM_LINE.match(block[j])
                                  or block[j].lstrip().startswith("#")
                                  and block[j].startswith((" ", "\t"))):
            j += 1
        return block[:i] + _render_list(key, items, indent, note=key == "include_titles") \
            + block[j:]
    return block + _render_list(key, items, "  ")


def sync_filters(cfg_path: str | Path, profile: dict) -> bool:
    """Rewrite the dynamic filter lists in config.yaml, in place. Everything
    else — thresholds, paths, comments, exclude_locations — is untouched.
    Returns False when there is no config file to tune."""
    path = Path(cfg_path)
    if not path.exists():
        return False
    updates = derive_filters(profile)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("filters:")), None)
    if start is None:
        lines += ["", _NOTE, "filters:"]
        lines += _render_list("include_titles", updates["include_titles"], "  ")
        lines += _render_list("exclude_titles", updates["exclude_titles"], "  ")
        if "locations" in updates:
            lines += _render_list("locations", updates["locations"], "  ")
    else:
        end = next((i for i in range(start + 1, len(lines)) if _TOP_KEY.match(lines[i])),
                   len(lines))
        block = lines[start:end]
        for key in _LIST_KEYS:
            if key in updates:
                block = _splice(block, key, updates[key])
        lines[start:end] = block
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
