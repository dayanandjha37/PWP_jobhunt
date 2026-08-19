"""Fetch jobs from public ATS APIs. No auth, no scraping, no ToS risk."""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable

import requests

UA = {"User-Agent": "jobhunt/1.0 (personal job search agent)"}
TIMEOUT = 20

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


@dataclass
class Job:
    job_id: str          # stable global id for dedupe: "<ats>:<slug>:<id>"
    ats: str
    company: str
    title: str
    location: str
    url: str
    description: str
    posted_at: str | None = None
    salary: str | None = None
    # filled in later by the pipeline
    score: float | None = None
    reason: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Adapters. Each takes the raw JSON body and returns list[Job].
# Keeping parse separate from HTTP is what makes offline testing possible.
# --------------------------------------------------------------------------

def parse_greenhouse(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        out.append(Job(
            job_id=f"greenhouse:{slug}:{j.get('id')}",
            ats="greenhouse",
            company=company,
            title=(j.get("title") or "").strip(),
            location=loc.strip(),
            url=j.get("absolute_url") or "",
            description=strip_html(j.get("content")),
            posted_at=j.get("updated_at") or j.get("first_published"),
        ))
    return out


def parse_lever(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or []):
        cats = j.get("categories") or {}
        # Lever splits the JD across descriptionPlain + a `lists` array.
        chunks = [j.get("descriptionPlain") or strip_html(j.get("description"))]
        for lst in (j.get("lists") or []):
            chunks.append(str(lst.get("text") or ""))
            chunks.append(strip_html(lst.get("content")))
        chunks.append(j.get("additionalPlain") or strip_html(j.get("additional")))
        ts = j.get("createdAt")
        posted = None
        if isinstance(ts, (int, float)):
            posted = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))
        out.append(Job(
            job_id=f"lever:{slug}:{j.get('id')}",
            ats="lever",
            company=company,
            title=(j.get("text") or "").strip(),
            location=(cats.get("location") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            description="\n\n".join(c for c in chunks if c).strip(),
            posted_at=posted,
            salary=cats.get("commitment"),
        ))
    return out


def parse_ashby(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        salary = None
        summary = comp.get("compensationTierSummary") or comp.get("summaryComponents")
        if isinstance(summary, str):
            salary = summary
        out.append(Job(
            job_id=f"ashby:{slug}:{j.get('id')}",
            ats="ashby",
            company=company,
            title=(j.get("title") or "").strip(),
            location=(j.get("location") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            description=(j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")) or "").strip(),
            posted_at=j.get("publishedAt"),
            salary=salary,
        ))
    return out


def parse_smartrecruiters(slug: str, company: str, body: Any) -> list[Job]:
    out = []
    for j in (body or {}).get("content") or []:
        loc = j.get("location") or {}
        # fullLocation is pre-joined but leaves blank segments ("Noida, , India");
        # either way, drop empty parts and rejoin.
        loc_str = loc.get("fullLocation") or ", ".join(
            p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
        loc_str = ", ".join(p.strip() for p in loc_str.split(",") if p.strip())
        out.append(Job(
            job_id=f"smartrecruiters:{slug}:{j.get('id')}",
            ats="smartrecruiters",
            company=company,
            title=(j.get("name") or "").strip(),
            location=loc_str,
            url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
            description="",  # JD lives on the per-posting endpoint, see below
            posted_at=j.get("releasedDate") or j.get("createdOn"),
        ))
    return out


def _smartrecruiters_jd(body: Any) -> str:
    sections = ((body or {}).get("jobAd") or {}).get("sections") or {}
    parts = [strip_html((sections.get(k) or {}).get("text"))
             for k in ("jobDescription", "qualifications", "additionalInformation")]
    return "\n\n".join(p for p in parts if p)


def parse_indeed(rows: Iterable[Any]) -> list[Job]:
    """JSONL rows written by the Indeed scraper (NaukriResumeUploader),
    camelCase IndeedJob shape. Rows without a jobId are dropped — an id-less
    row can never dedupe against seen.json."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        jk = str(r.get("jobId") or r.get("jk") or "").strip()
        if not jk:
            continue
        if not jk.startswith("indeed:"):
            jk = f"indeed:{jk}"
        out.append(Job(
            job_id=jk,
            ats="indeed",
            company=str(r.get("company") or "Unknown").strip(),
            title=str(r.get("title") or "").strip(),
            location=str(r.get("location") or "").strip(),
            url=str(r.get("url") or ""),
            description=str(r.get("description") or "").strip(),
            posted_at=r.get("postedAt"),
            salary=r.get("salary"),
        ))
    return out


ENDPOINTS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever":      ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby":      ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
}

SR_LIST = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
SR_DETAIL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}"

# SmartRecruiters' list endpoint carries no JD text — the description is one
# extra request per posting, and boards run 500+ postings. Detail-fetch only
# engineering- or recruiting-looking titles, capped: prefilter still makes the
# real keep/drop call, this regex is purely request-budget control. Recruiting
# terms matter for non-engineering users (talent/HR roles screened on an empty
# JD otherwise).
SR_DETAIL_TITLE = re.compile(
    r"\b(software|backend|frontend|full.?stack|platform|infra|devops|sre|"
    r"site reliability|systems|network|kernel|data|cloud|security|qa|"
    r"developer|engineer|architect|talent|recruit|sourcer|people|"
    r"human resources|hr)\b", re.I)
SR_DETAIL_CAP = 150


def fetch_smartrecruiters(slug: str, company: str,
                          session: requests.Session) -> list[Job]:
    """SmartRecruiters needs paging + a per-posting detail pass, so it gets its
    own fetcher instead of the one-shot ENDPOINTS table."""
    jobs: list[Job] = []
    offset = 0
    while True:
        try:
            r = session.get(SR_LIST.format(slug=slug, offset=offset),
                            headers=UA, timeout=TIMEOUT)
            if r.status_code != 200:
                print(f"  ! smartrecruiters/{slug} -> HTTP {r.status_code}")
                return jobs
            page = r.json()
        except Exception as e:
            print(f"  ! smartrecruiters/{slug} -> {type(e).__name__}: {e}")
            return jobs
        content = page.get("content") or []
        jobs.extend(parse_smartrecruiters(slug, company, page))
        offset += len(content)
        if not content or offset >= (page.get("totalFound") or 0):
            break
        time.sleep(0.2)

    todo = [j for j in jobs if SR_DETAIL_TITLE.search(j.title)][:SR_DETAIL_CAP]
    for j in todo:
        jid = j.job_id.rsplit(":", 1)[-1]
        try:
            r = session.get(SR_DETAIL.format(slug=slug, jid=jid),
                            headers=UA, timeout=TIMEOUT)
            if r.status_code == 200:
                j.description = _smartrecruiters_jd(r.json())
        except Exception:
            pass  # keep the listing; prefilter can still run on title+location
        time.sleep(0.05)
    return jobs


def fetch_board(ats: str, slug: str, company: str | None = None,
                session: requests.Session | None = None) -> list[Job]:
    """Hit one company's public board. Returns [] on any failure (never raises)."""
    sess = session or requests
    if ats == "smartrecruiters":
        return fetch_smartrecruiters(slug, company or slug, sess)
    if ats not in ENDPOINTS:
        raise ValueError(f"unknown ATS: {ats}")
    url_tpl, parser = ENDPOINTS[ats]
    try:
        r = sess.get(url_tpl.format(slug=slug), headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"  ! {ats}/{slug} -> HTTP {r.status_code}")
            return []
        return parser(slug, company or slug, r.json())
    except Exception as e:  # dead slug, rate limit, network blip
        print(f"  ! {ats}/{slug} -> {type(e).__name__}: {e}")
        return []


def fetch_indeed(path: str | Path) -> list[Job]:
    """Read the shared Indeed JSONL export (one job per line, written by the
    Java scraper). Returns [] on a missing file or bad lines — the same
    never-raise contract as fetch_board."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"  ! indeed -> {type(e).__name__}: {e}")
        return []
    rows: list[Any] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            print(f"  ! indeed: skipping malformed line in {p.name}")
    return parse_indeed(rows)


def fetch_all(companies: Iterable[dict], sleep: float = 0.25) -> list[Job]:
    jobs: list[Job] = []
    session = requests.Session()
    for c in companies:
        got = fetch_board(c["ats"], c["slug"], c.get("name"), session=session)
        if got:
            print(f"  {c.get('name') or c['slug']:<28} {len(got):>4} jobs  ({c['ats']})")
        jobs.extend(got)
        time.sleep(sleep)
    return jobs
