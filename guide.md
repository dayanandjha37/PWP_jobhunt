# Multi-User Guide — Running Job Hunt Pipelines for Multiple People

This guide explains how to run the jobhunt pipeline for multiple users on one
machine. Each user gets their own fully isolated workspace: their resume
profile, their company list, their API keys, their SMTP credentials, their
dedupe history, and their own email digest.

Nothing is shared between users at run time.

---

## 1. Prerequisites

- Python 3.11+ with the package dependencies installed:

  ```bash
  pip install -r requirements.txt
  ```

- One LLM API key per user (Gemini / Anthropic / Groq — any supported
  provider). For offline testing no key is needed at all (see §5).
- One Gmail **App Password** per user if they want the digest emailed
  (regular login passwords do not work with SMTP — create one at
  Google Account → Security → 2-Step Verification → App Passwords).
- Python must run from the project root for the commands below:
  `/Users/DAYAN/PycharmProjects/PWP_jobhunt`.

---

## 2. How it works (30-second version)

Every user lives in one directory under `users/`:

```
users/<name>/
  config.yaml      their filters, thresholds and file paths
  .env             their secrets: API key, SMTP credentials, MAIL_TO
  companies.yaml   their list of companies to scan ({ats, slug, name})
  resume.pdf       their resume (.pdf/.txt/.md; consumed once, then optional)
  profile.json     built automatically from the resume on their first real run
  seen.json        their dedupe + application tracker (created on first run)
  inbox/           Indeed job exports land here (auto-created)
  out/             their digest.html + tracker.csv (auto-created)
```

One command runs everyone:

```bash
python -m jobhunt run-all
```

For each user directory the tool:

1. Changes into that user's directory (so all paths in their `config.yaml`
   resolve inside their workspace).
2. Loads that user's `.env` and applies it **scoped** — their values
   override the environment during their run and the previous values are
   restored afterwards. User A's API key can never leak into user B's run.
3. Runs the full pipeline with their config: fetch → prefilter → screen →
   draft → digest → email.
4. Moves on to the next user. If one user fails (bad key, network, crash),
   the sweep continues and the failure is reported in the summary.

The per-user pipeline is the same single-user pipeline as before — only the
workspace and credentials differ.

---

## 3. Adding a new user

### Step 1 — Create the directory and copy the scaffold

```bash
cd /Users/DAYAN/PycharmProjects/PWP_jobhunt
cp -R users/sample users/<name>          # e.g. users/priya
rm -f users/<name>/seen.json users/<name>/out/digest.html users/<name>/out/tracker.csv 2>/dev/null
```

The scaffold gives you a working `config.yaml`, an `.env` template and a
`companies.yaml`. Clean state files so the new user starts fresh.

### Step 2 — Fill in their secrets (`users/<name>/.env`)

Uncomment and set the values that user needs. Example for a Gemini user:

```dotenv
SCREEN_PROVIDER=gemini
SCREEN_MODEL=gemini-2.5-flash
DRAFT_PROVIDER=gemini
DRAFT_MODEL=gemini-2.5-pro
GEMINI_API_KEY=their-key-here

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=them@gmail.com
SMTP_PASS=their-gmail-app-password
MAIL_TO=them@gmail.com
```

- Provider/model variables are optional — sensible defaults apply.
- Leave SMTP variables commented out to skip email (digest still written to
  their `out/digest.html` unless `--send` is passed; email is only attempted
  with `--send`).

### Step 3 — Tune their filters (`users/<name>/config.yaml`)

Edit at minimum:

- `filters.include_titles` / `exclude_titles` — job titles they want/don't
  want. Regexes, matched case-insensitively against the title only.
- `filters.locations` — substrings matched against location; add their city.
- `filters.max_age_days`, `score_threshold`, `max_per_digest` as preferred.

All paths in this file are **relative to the user directory** — do not point
them at another user's files.

### Step 4 — Set their company list (`users/<name>/companies.yaml`)

```yaml
companies:
  - {ats: greenhouse, slug: stripe, name: Stripe}
  - {ats: lever,      slug: ramp,   name: Ramp}
  - {ats: ashby,      slug: linear, name: Linear}
```

Only public ATS boards (greenhouse / lever / ashby) are supported. No auth
needed.

### Step 5 — Drop their resume into the user directory

Copy their resume in as `users/<name>/resume.pdf` (or `resume.txt` /
`resume.md` — any one file named `resume.*`):

```bash
cp /path/to/their/resume.pdf users/<name>/
```

Nothing else to do. On their **first real run** the pipeline notices
`profile.json` is missing, finds the resume in the user directory, and builds
the profile automatically — one call to that user's own draft LLM, using their
own scoped `.env` key (never the root one). The built `profile.json` is
written next to the resume and reused on every later run.

Details:

- `--mock` runs never call the LLM, so they use the bundled sample profile
  and leave the resume untouched — the first *real* run does the build.
- A different filename works too: set `resume_file: cv.txt` in their
  `config.yaml`.
- Manual build for one user, on demand (uses their `.env` key and their
  `resume.*`, writes their `profile.json`):
  ```bash
  python -m jobhunt profile --user <name>
  ```
- PDF needs Gemini or Anthropic; on Groq/Ollama export the resume to `.txt`.
- After the first real run the resume file itself is no longer read — only
  `profile.json` is. Check it (years of experience, target titles, core
  skills) since every score is measured against it.

### Step 6 — First run (offline sanity check, no API cost)

```bash
python -m jobhunt run-all --mock --scorer keyword --user <name>
```

Expect: funnel counts on screen, `users/<name>/out/digest.html` written,
`seen.json` created. Run it twice — the second run should say
"nothing new today" (per-user dedupe works).

### Step 7 — Real run

```bash
python -m jobhunt run-all --user <name>            # screen + draft, no email
python -m jobhunt run-all --user <name> --send     # also email the digest
python -m jobhunt run-all                          # everyone, sequential
```

The user is now part of every sweep. Done.

---

## 4. Everyday commands

| Command | What it does |
|---|---|
| `python -m jobhunt run-all` | Run every user under `users/`, sequentially |
| `python -m jobhunt run-all --user <name>` | Run one user |
| `python -m jobhunt run-all --send` | Also email each user their digest |
| `python -m jobhunt run-all --mock --scorer keyword` | Offline dry run, no API keys, no network |
| `python -m jobhunt run-all --limit 20` | Cap jobs sent to the LLM per user (cost guard) |
| `python -m jobhunt run-all --no-draft` | Skip the expensive drafting stage |
| `python -m jobhunt profile --user <name>` | Build one user's profile.json now (their `.env`, their resume) |
| `python -m jobhunt run --config users/<name>/config.yaml` | Run one user without the sweep wrapper |
| `python -m jobhunt stats --config users/<name>/config.yaml` | Tracker summary + CSV for one user |
| `python -m jobhunt applied <job_id> --config users/<name>/config.yaml` | Mark a job as applied for one user |

Notes:

- `--send` is opt-in per invocation; without it the digest is only written
  to disk.
- A user failing never stops the others — the final line reports
  `run-all: N/M ok, failed: ...`.
- The agent **never submits applications**. It finds, filters, scores and
  drafts; the human reads the digest and applies.

---

## 5. Indeed job exports (inbox)

The Java scraper (NaukriResumeUploader) exports Indeed jobs as one JSON file
per job into a user's `inbox/` directory:

```json
{"job_id": "abc123", "source": "indeed", "title": "Backend Engineer",
 "company": "Acme", "location": "Bengaluru, India",
 "url": "https://in.indeed.com/viewjob?jk=abc123",
 "description": "...", "fetched_at": "2026-08-15T09:00:00+05:30"}
```

On the next pipeline run these are imported automatically:

- valid files are turned into jobs (`job_id` becomes
  `indeed:indeed:abc123` so they dedupe like every other source) and moved to
  `inbox/archive/`,
- malformed files move to `inbox/failed/` and never crash the run,
- an empty or missing `inbox/` is fine.

To hand-test the flow, drop a file like the one above into
`users/<name>/inbox/` and run the pipeline.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `no users/ directory — nothing to run` | Create `users/<name>/` or copy the scaffold (§3) |
| User skipped: `config.yaml missing` | Every user directory must contain `config.yaml` |
| `screening scored nothing: every batch failed` | Bad API key, rate limit or wrong model id. Jobs are NOT recorded as seen — fix the key and rerun. |
| Email failed, digest still on disk | Wrong app password or blocked port. Check `SMTP_PASS` is a Gmail App Password. |
| Same jobs reappearing for a new user | They were given a copied `seen.json` — delete it (§3 step 1). |
| One user's key used for another | Not possible by design: `.env` values are applied scoped and restored after each user's run. |
| `missing profile.json` | Drop `resume.pdf`/`.txt`/`.md` into the user directory — the next real run builds it (§3 step 5). `--mock` runs fall back to the bundled example profile. |
| `profile build failed` | Real run found the resume but the LLM call failed: bad key in that user's `.env`, wrong model id, or a PDF on a text-only provider (use `.txt`). The run aborts before recording any jobs — fix and re-run. |

---

## 7. Scheduling

The pipeline does not schedule itself. The Spring app (ResumeTransformer)
owns the daily schedule: it runs `run-all`-equivalent per-user runs for all
enabled users at 07:15 daily, plus a per-user "Run now" button in its UI.
See PLAN.md in the Job-application-assistant repository for details.
