# PLAN-CI.md — Multi-user CI: every user searched, pausable, deletable

> Same rules as PLAN.md: checkpointable stories, tick the checkbox and add a
> session note after each, **no secret values in this file** — names only.

---

## Background

CI (`.github/workflows/daily.yml`) runs single-user root mode: one
`PROFILE_JSON` secret, root `config.yaml`, root `seen.json` cache. Only
`dayanand` is wired. This plan makes CI serve every user in `users/` with:

- **R1** each listed user's job search runs in CI
- **R2** deleting a local user dir prunes their GitHub secrets
- **R3** pausing a user (no deletion) stops their digest, keeps secrets,
  resumes instantly — local marker file + web UI button

Decisions (2026-08-18):

- User list = GitHub variable `USERS` (JSON array, e.g. `["dayanand","piyush"]`)
- ONE shared LLM key (`LLM_API_KEY` secret + provider repo vars) for everyone
- Per-user SMTP secrets (`SMTP_USER_<NAME>` etc.) — each user's digest emails
  from their own address
- `users/sample/` scaffold kept, always excluded
- Pause marker: `users/<name>/.paused` (gitignored, empty file)

Local machinery reused unchanged: `python -m jobhunt run-all --user <name>`
chdirs into `users/<name>/` and scopes its `.env` (jobhunt/cli.py:306,
jobhunt/userenv.py). CI only materializes each workspace.

Mechanics validated against GitHub docs: `secrets[format('PROFILE_JSON_%s',
matrix.user)]` resolves per-user secrets in step env (missing → empty string);
empty `USERS` guarded by a plan job; secret names restricted to
`[A-Za-z0-9_]` (keeps per-user cache-key prefixes collision-free); repo
secret cap 100 ≈ 13 users at 7 secrets each; `vars` are public on a public
repo — usernames only, never values.

---

## Story M1 — Sync script + offline tests

Create `scripts/users_sync.py`:

- `discover_users()` — dirs under `users/` minus `sample`; warn+skip names
  outside `[A-Za-z0-9_]`; `paused` = `.paused` file exists
- `build_plan(users, remote_secret_names)` — PURE: returns set/delete/variable
  actions. Upserts per-user secrets for ALL local users incl. paused
  (unpause = rerun sync): `PROFILE_JSON_<U>` from `profile.json` (must parse,
  else hard error naming the user), `CONFIG_YAML_<U>` from `config.yaml`,
  `SMTP_{HOST,PORT,USER,PASS}_<U>` + `MAIL_TO_<U>` from the user `.env`
  (empty values skipped, never set empty; warn on missing SMTP_PASS; warn on
  local LLM keys — CI uses the shared key). Deletes remote per-user secrets
  whose local dir is gone (R2). Sets `USERS` = sorted non-paused (R3).
- `apply_plan()` — gh subprocess; secret values via stdin only, never argv
- `main()` — `--dry-run --yes --repo`; preflight `gh auth status`; dry-run
  prints names + byte sizes only

Create `tests/test_users_sync.py` — offline, fake `gh` runner injected.

- [x] Done

*Test:* `pytest tests/` green (138 + 11 new = 149). Dry-run against the real
repo: 14 actions (7 secrets/user + USERS var), warnings for piyush's missing
SMTP_PASS and both users' local LLM keys, no values printed.

*Session note:* 2026-08-18 — committed `ba1edf9` on `ciissues`.

## Story M2 — First real sync

```bash
python scripts/users_sync.py --dry-run   # review names/sizes
python scripts/users_sync.py --yes
gh secret list
gh variable get USERS
```

Old root secrets untouched — current workflow unaffected.

- [x] Done

*Test:* per-user secret names present; `USERS` = `["dayanand", "piyush"]`;
shared `LLM_API_KEY` + provider vars set (`LLM_PROVIDER=openai-compatible`,
`SCREEN_MODEL=glm-5.2`, `DRAFT_MODEL=glm-5.2`,
`LLM_BASE_URL=https://api.z.ai/api/coding/paas/v4/`). Legacy `PROFILE_JSON`
still present (deleted in M5).

*Session note:* 2026-08-18 — sync ran clean; 14 secrets + USERS + 4 vars +
LLM_API_KEY. piyush has no SMTP_PASS yet (warned, digest will not email).

## Story M3 — Workflow rewrite, verified on branch

Branch `ci-multiuser`. Rewrite `daily.yml`:

- `plan` job: validates `vars.USERS` (JSON array of `[A-Za-z0-9_]` strings,
  dedupes, strips `sample` with warning) → `outputs.matrix`; malformed →
  red `::error::` naming the fix command
- `digest` job: `if: matrix != '[]'`; `matrix.user` from plan output;
  `fail-fast: false`; `concurrency: jobhunt-<user>` (per-user queue, users
  parallel)
- cache `users/<u>/seen.json`, key `jobhunt-seen-<u>-${{ github.run_id }}`,
  restore-keys `jobhunt-seen-<u>-`
- Materialize step — ONLY secrets touchpoint, all via `secrets[format(...)]`:
  `profile.json` (empty → `::error::` naming sync), `config.yaml` from
  `CONFIG_YAML_<U>` else `cp` of root config.yaml, `.env` written by inline
  Python from `os.environ` (no shell interpolation), empty keys omitted
- `python -m jobhunt run-all --user <u>` (+ `--send` unless `dry_run`)
- artifact `digest-<u>-<run_number>` from `users/<u>/out/`; per-user dedupe
  report. Cron + permissions unchanged.

- [ ] Done

*Test:* `gh workflow run daily.yml --ref ci-multiuser -f dry_run=true` → two
digest jobs green, materialize logs `profile.json parsed OK`, artifacts
exist, `gh cache list` shows per-user entries, screening passes on the
shared GLM key.

## Story M4 — Merge + prime + first real email

Merge to main. Per-user `dry_run=true` dispatch (primes cold per-user
`seen.json` caches, no email), then `dry_run=false`.

- [ ] Done

*Test:* digests email per user with SMTP configured; piyush (no SMTP_PASS)
still green with email-skip warning, digest in artifact.

## Story M5 — Legacy secret cleanup

```bash
gh secret delete PROFILE_JSON
gh secret delete SMTP_HOST
gh secret delete SMTP_PORT
gh secret delete SMTP_USER
gh secret delete SMTP_PASS
gh secret delete MAIL_TO
```

Keep `LLM_API_KEY` + provider vars.

- [ ] Done

*Test:* `gh secret list` shows only the new scheme; one more dispatch green.

## Story M6 — Pause button in web UI

`jobhunt/server.py`: POST route toggling `users/<name>/.paused`, then spawns
`python scripts/users_sync.py` (same subprocess pattern as the Run button).
Template: per-user "Pause CI"/"Resume CI" button.

- [ ] Done

*Test:* click Pause on piyush → `gh variable get USERS` → `["dayanand"]` →
dispatch runs ONE matrix job; resume restores two.

## Story M7 — Local pause semantics + docs

`jobhunt/cli.py`: `run-all` without `--user` skips `.paused` users; explicit
`--user` overrides. Extract `_user_dirs()` helper + test. Rewrite README
"Scheduling" + SETUP.md Step 12 for the multi-user flow. Tick PLAN.md
Story 7, point it at this file.

- [ ] Done

*Test:* `pytest` green; `touch users/piyush/.paused && python -m jobhunt
run-all` runs dayanand only; docs match reality.

---

## Ground rules

Same as PLAN.md: never paste secret values anywhere; `safe-commit` before
every commit; tick + session-note after each story.

## Session log

- 2026-08-18 — Plan written (replaces PLAN.md Story 7, pulled forward by
  user request). Start at Story M1.
