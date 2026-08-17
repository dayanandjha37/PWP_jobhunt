---
name: safe-commit
description: Leak-guard then commit. Scan the pending diff for secrets and personal data (API keys, .env values, resumes, profile.json, seen.json, emails) BEFORE committing this jobhunt repo, run the tests, then commit with a conventional message. Use whenever the user asks to commit, save, or check in changes in this project.
---

# safe-commit

Commit pipeline for PWP_jobhunt. This repo carries real people's job-search
data (resumes, profiles, application trackers, mailbox credentials), so every
commit runs the leak guard first. Never skip it because "it's just code".

## 1. Scope what will be committed

- `git status --porcelain` — list every modified/untracked path.
- Anything under `users/<name>/` other than `users/sample/` scaffold files
  (config.yaml) is personal: refuse to commit it. Verify with
  `git check-ignore -v <path>` — if it is NOT ignored, the .gitignore has a
  gap: fix .gitignore first, then continue.
- Never stage with wildcards that can sweep ignored-but-present files
  (e.g. do not `git add users/`). `git add -A` is acceptable ONLY after the
  check-ignore verification above passed for every new path.

## 2. Secret scan (values, not names)

Run over the to-be-committed diff (`git diff` / `git diff --cached` / file
contents of new untracked files):

```
grep -inE "sk-[a-zA-Z0-9]{8,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]|gho_[a-zA-Z0-9]|xox[baprs]-|AIza[a-zA-Z0-9_-]{10,}|Bearer [a-zA-Z0-9._-]{16,}"
```

Plus the semantic checks:

- `.env`, `*.env` files, or `KEY=value` lines: a var NAME or an empty value
  is fine; any non-empty secret-looking value is a leak.
- GitHub Actions files: `${{ secrets.NAME }}` and `${{ vars.NAME }}` refs are
  SAFE (they are lookups, not values). A hardcoded value next to them is a leak.
- `SMTP_PASS`, `SMTP_USER` (email address), API keys: names in docs/README
  tables are fine; values anywhere are a leak.
- High-entropy strings >32 chars in new config/data files: inspect before
  passing them.

## 3. PII scan

Grep the diff and new files for personal data:

- Email addresses: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,}` (example.com
  placeholders are fine; gmail/outlook/personal domains are not).
- Real names + phone numbers in config or fixture files.
- These must never be tracked: `resume.*`, `profile.json` (except
  `profile.example.json`), `seen.json`, `out/`, `users/*/.env`,
  `users/*/inbox/`, `users/*/out/`.

If a scan hits: STOP. Show the finding, do not commit. Fix by adding the path
to .gitignore or replacing the value with a placeholder. If the secret was
already committed in an earlier revision, say so and offer
`git filter-repo` / credential rotation — do not silently move on.

## 4. Test, then commit

- `python3 -m pytest tests/ -q` — all green before committing. A failing
  suite means report, not commit.
- Conventional message matching repo history (`feat:`, `fix:`, `chore:` …),
  body wrapped at ~72 cols, ending with:

  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

- Commit only what the user asked for; if the branch is `main`, create a
  branch first unless the user said to commit on `main`.
- Do not push unless asked.
- Report the commit hash and the one-line leak-scan verdict (clean / findings
  fixed) in the final answer.
