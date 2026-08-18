# PLAN.md — Get the daily job digest running in CI, with zero leaks

> **How to use this file:** this is a checkpointable plan. Each story is small,
> ends in a visible win, and has a checkbox. When a session ends or context
> fills, open the next unchecked story and continue from there. Update the
> checkbox and the "Session notes" line at the bottom of the story when done.
> This file contains **no secrets** — only secret *names* and file paths.

---

## Background (why this plan exists)

The repo `PWP_jobhunt` is a personal job-search agent. A GitHub Actions workflow
(`.github/workflows/daily.yml`) runs it every weekday at 06:00 IST and emails a
digest of new, resume-matched job postings. The agent never submits
applications — it finds, filters, scores, drafts; a human presses submit.

All sensitive material is deliberately gitignored so nothing leaks:

- `.env` — API keys
- `profile.json` — derived from a resume (personal)
- `resume.*` — the resume itself
- `seen.json` — per-user dedupe store
- `users/*` — per-user workspaces (keys, resume, profile, out/, inbox/)
  except the `users/sample/` scaffold

Because of that, CI must reconstruct the sensitive inputs from **GitHub repo
secrets** at runtime. That wiring was never finished: the first scheduled run
(2026-08-18, run id 32090155022) failed at the "Write profile.json" step
because the `PROFILE_JSON` secret is empty/missing, and everything after it was
skipped.

## Current state (verified 2026-08-18)

- Gitignore is working: only `users/sample/config.yaml` is tracked under
  `users/`. Real users `dayanand` and `piyush` are fully local-only, each with
  `.env`, `config.yaml`, `profile.json`, `resume.*`, `seen.json`, `inbox/`, `out/`.
- The workflow runs **root-level single-user mode**: `python -m jobhunt run`
  with the root `config.yaml`. It does NOT use `run-all` / `users/`.
- Local machine has **no `gh` CLI** and no root `profile.json` / `.env` —
  only the per-user ones under `users/<name>/`.
- Repo is public (`github.com/dayanandjha37/PWP_jobhunt`), so Actions minutes
  are free and unlimited on standard runners. Cost is not a concern.
- Secret inventory needed by the workflow (see `daily.yml`): `PROFILE_JSON`,
  `ANTHROPIC_API_KEY` (or GLM provider vars), `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASS`, `MAIL_TO`.
- Guard already in place: the `safe-commit` skill scans every commit for
  secrets before committing. Keep using it.

## Key code references

| What | Where |
|---|---|
| Workflow definition | `.github/workflows/daily.yml` |
| Pipeline orchestration | `jobhunt/cli.py` → `cmd_run` (~line 183) |
| Multi-user sweep | `jobhunt/cli.py` → `cmd_run_all` |
| Provider/key resolution | `jobhunt/providers.py` → `resolve()` |
| Email sending | `jobhunt/mailer.py` |
| Dedupe store | `jobhunt/store.py` |

---

## Story 1 — Prove nothing ever leaked (git history audit)

`.gitignore` blocks *future* commits; it does nothing about what is already in
history. Audit the full history for sensitive paths ever having been committed.

Commands:

```bash
# What is tracked right now (should show no .env/profile/resume/seen.json)
git ls-files

# Did any sensitive path EVER exist in history on any branch?
git log --all --oneline --diff-filter=A -- .env 'users/*/.env' \
  'users/*/profile.json' 'profile.json' 'resume.*' 'users/*/resume.*' \
  'seen.json' 'users/*/seen.json'
```

- [x] Done

*Finding:* `seen.json` (218 lines, job postings + scores) was committed in
`b5f49f2` (2026-08-09) and stayed in history even after `1eb402e` untracked
it. No keys/tokens/emails in it; full-history scan for secret patterns came
back clean, so no key rotation needed. Purged with
`git filter-repo --path seen.json --invert-paths --force` (v2.47.0), backup
bundle kept at `../pre-purge-backup.bundle`, force-pushed `main` + `ciissues`.
Note: old commits may survive under GitHub's hidden `refs/pull/*` archive —
harmless here (no secrets), needs GitHub Support to fully drop.

*Learned:* tracked vs ignored vs history; `git log --diff-filter=A`.

## Story 2 — Install `gh` CLI and authenticate

Everything after this becomes one-line commands instead of web-UI copy-paste.

```bash
brew install gh
gh auth login          # choose GitHub.com, HTTPS, login with browser
gh auth status
gh repo set-default dayanandjha37/PWP_jobhunt   # optional convenience
```

- [x] Done

*Learned:* gh CLI basics, OAuth scopes (`repo`, `workflow` needed for later
stories — `gh auth refresh -s workflow` if a workflow edit is rejected).

*Note:* authed as `dayanandjha37`, scopes `gist read:org repo` — sufficient
for `gh secret set` / `gh variable set`. Git push goes over SSH, so workflow
file edits via git are unaffected by the missing `workflow` scope.

## Story 3 — Set `PROFILE_JSON`, run the workflow manually

CI writes `profile.json` from the `PROFILE_JSON` secret, then validates it as
JSON. Reuse the existing local profile — no LLM call, no resume re-upload:

```bash
gh secret set PROFILE_JSON < users/dayanand/profile.json
gh secret list           # confirm it is there (name only, never the value)

# Trigger a manual run with dry_run=true (builds digest artifact, skips email)
gh workflow run daily.yml -f dry_run=true
gh run watch             # or: gh run list --workflow=daily.yml --limit 1
gh run view --log-failed # if it fails, read the actual error
```

- [x] Done

Run 32134367735 (dry_run=true): "Write profile.json" ✓, fetch ✓ (4455 jobs),
prefilter ✓ (36 new), digest artifact ✓. Pipeline step failed exactly as
predicted: `ANTHROPIC_API_KEY is not set` — Story 4 signal.

*Learned:* what a secret is (encrypted at rest, injected as env at runtime,
never echoed in logs), `workflow_dispatch` inputs, run artifacts, reading
failed-step logs with `gh run view --log-failed`.

## Story 4 — LLM key secret

CI needs whichever provider the root `config.yaml` / repo vars select.
Check first:

```bash
cat config.yaml                     # screen/draft provider settings
gh variable list                    # LLM_PROVIDER, SCREEN_PROVIDER, ...
cat users/dayanand/.env             # which key the working local setup uses
```

Then set the matching secret(s):

```bash
gh secret set ANTHROPIC_API_KEY < <key-file-or-paste>
# or, for the GLM/openrouter-style setup:
gh secret set LLM_API_KEY   < <key-file-or-paste>
gh variable set LLM_BASE_URL --body "<base-url-if-used>"
```

Re-run `gh workflow run daily.yml -f dry_run=true` and check that screening
and drafting pass and the digest artifact contains scored jobs with drafts.

- [ ] Done

*Learned:* how `jobhunt/providers.py:resolve()` maps env vars → provider.

## Story 5 — SMTP secrets, first real email

```bash
gh secret set SMTP_HOST --body "smtp.gmail.com"        # adjust provider
gh secret set SMTP_PORT --body "587"
gh secret set SMTP_USER --body "<your address>"
gh secret set SMTP_PASS --body "<app password>"        # Gmail: app password, NOT login
gh secret set MAIL_TO   --body "<digest recipient>"
gh workflow run daily.yml -f dry_run=false
```

Gmail app password: Google Account → Security → 2-Step Verification →
App passwords. Note: a mail failure does NOT fail the job — `cli.py` catches
it (~line 290) and keeps the digest on disk/artifact.

- [ ] Done

*Learned:* SMTP auth, app passwords, why mail errors are non-fatal.

## Story 6 — Verify cron fires and the dedupe cache survives

Two things to confirm across two consecutive runs:

1. Cache restore: the "Report the dedupe store" step should print
   `tracking N postings` (not "no seen.json") on the second run, and no job
   should appear twice across digests.
2. Scheduled trigger: the run appears by itself on the next weekday
   (~06:00 IST / 00:30 UTC; GitHub cron can lag a few minutes).

Useful:

```bash
gh run list --workflow=daily.yml --limit 5
gh run view <id> --log | grep -A2 "dedupe"
```

Known rule: GitHub auto-disables scheduled workflows after 60 days of repo
inactivity (no pushes). Any commit resets it.

- [ ] Done

*Learned:* `actions/cache` immutable keys + `restore-keys`, scheduler
best-effort behavior, the 60-day rule.

## Story 7 — Multi-user CI

Pulled forward by user decision (2026-08-18): multi-user CI chosen (option B,
extended with pause + delete-sync). Full story plan now lives in
**PLAN-CI.md** — follow that file from Story M1.

- [x] Done (decision: multi-user, per-user SMTP, shared LLM key; see PLAN-CI.md)

---

## Ground rules while executing this plan

1. Never paste an actual secret value into chat, PLAN.md, or a commit — only
   secret names.
2. Run the `safe-commit` skill before any commit.
3. After each story: tick its checkbox, append a one-line session note
   (date + what happened) so the next session can resume cold.
4. `PLAN.md` itself contains nothing sensitive; committing it is fine but
   optional.

## Session log

- 2026-08-18 — Plan written. No stories executed yet. Start at Story 1.
- 2026-08-18 — Story 1 done: found + purged `seen.json` from history
  (no secrets in it, no rotation needed), force-pushed rewritten `main` +
  `ciissues`. Next: Story 2 (install `gh` CLI).
- 2026-08-18 — Story 2 done: `gh` 2.97.0 installed, authed as
  `dayanandjha37` (scopes gist/read:org/repo), default repo set. Next:
  Story 3 (`PROFILE_JSON` secret + manual dry run).
- 2026-08-18 — Story 3 done: `PROFILE_JSON` secret set from
  `users/dayanand/profile.json`, dry run 32134367735 — profile write,
  fetch, prefilter, artifact all green; failed only on missing
  `ANTHROPIC_API_KEY`. Next: Story 4 (LLM key secret).
