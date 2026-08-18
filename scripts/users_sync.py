#!/usr/bin/env python3
"""Sync local users/ to GitHub: per-user secrets + the USERS variable.

Local `users/` (minus `sample/`) is the source of truth:

  - every local user gets per-user secrets refreshed — paused users too, so
    unpausing is just a rerun of this script
  - a per-user secret whose local user dir is gone gets deleted
  - `users/<name>/.paused` stops the CI digest without deleting anything:
    the user drops out of the USERS variable, their secrets stay

Secret VALUES only ever travel file -> gh stdin. Never argv, never stdout;
the dry-run prints names and byte sizes and nothing else.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt.userenv import parse_env_file  # noqa: E402 - after path setup

ROOT = Path(__file__).resolve().parent.parent

# GitHub secret names allow [A-Za-z0-9_] only — this also keeps per-user
# cache-key prefixes collision-free in the workflow.
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
PER_USER_RE = re.compile(
    r"^(PROFILE_JSON|CONFIG_YAML|SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASS|MAIL_TO)_([A-Za-z0-9_]+)$"
)
SMTP_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_TO")
# CI deliberately uses the one shared LLM_API_KEY + provider repo vars; a
# local per-user key is fine for local runs but is never synced.
LLM_KEYS = ("LLM_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY")
SECRET_CAP_SOFT = 80  # GitHub hard cap is 100; warn before hitting it


class SyncError(RuntimeError):
    """A local user is not syncable — fix the named file and rerun."""


@dataclass
class UserSpec:
    name: str
    paused: bool


@dataclass
class SetSecret:
    name: str
    value: bytes


@dataclass
class DeleteSecret:
    name: str


@dataclass
class SetVariable:
    name: str
    value: str


@dataclass
class Plan:
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def discover_users(users_dir: Path) -> tuple[list[UserSpec], list[str]]:
    """Every dir under users/ except `sample` (the scaffold). Names outside
    [A-Za-z0-9_] cannot have GitHub secrets — warn and skip."""
    users: list[UserSpec] = []
    warnings: list[str] = []
    if not users_dir.is_dir():
        return users, warnings
    for d in sorted(users_dir.iterdir()):
        if not d.is_dir():
            continue
        if d.name == "sample":
            continue
        if not NAME_RE.match(d.name):
            warnings.append(
                f"{d.name}: chars outside [A-Za-z0-9_] — no GitHub secret name "
                f"is possible; skipped")
            continue
        users.append(UserSpec(name=d.name, paused=(d / ".paused").exists()))
    return users, warnings


def build_plan(users: list[UserSpec], users_dir: Path,
               remote_names: set[str]) -> Plan:
    """Decide every gh action. Reads local files, touches nothing remote."""
    import yaml  # same dependency the CLI already uses for config.yaml

    plan = Plan()
    local = {u.name.casefold() for u in users}
    errors: list[str] = []

    for u in users:
        secret_suffix = u.name.upper()
        # profile.json — must exist and parse; a broken one aborts the sync
        # so we never half-update GitHub.
        profile_path = users_dir / u.name / "profile.json"
        try:
            profile_bytes = profile_path.read_bytes()
            json.loads(profile_bytes)
        except (OSError, ValueError) as e:
            errors.append(f"{u.name}: profile.json missing or not valid JSON ({e})")
            continue
        plan.actions.append(
            SetSecret(f"PROFILE_JSON_{secret_suffix}", profile_bytes))

        # config.yaml — required by `run-all` locally, so require it here too.
        config_path = users_dir / u.name / "config.yaml"
        try:
            config_bytes = config_path.read_bytes()
            yaml.safe_load(config_bytes)
        except (OSError, yaml.YAMLError) as e:
            errors.append(f"{u.name}: config.yaml missing or not valid YAML ({e})")
            continue
        plan.actions.append(
            SetSecret(f"CONFIG_YAML_{secret_suffix}", config_bytes))

        env = parse_env_file(users_dir / u.name / ".env")
        if any(k in env for k in LLM_KEYS):
            plan.warnings.append(
                f"{u.name}: .env has its own LLM key(s) — not synced; CI uses "
                f"the shared LLM_API_KEY secret")
        for key in SMTP_KEYS:
            value = env.get(key, "").strip()
            if not value:  # never set an empty secret; empty means "default"
                if key == "SMTP_PASS" and env.get("SMTP_USER", "").strip():
                    plan.warnings.append(
                        f"{u.name}: SMTP_PASS not set — CI digest will build "
                        f"but not email until added")
                continue
            plan.actions.append(SetSecret(f"{key}_{secret_suffix}", value.encode()))

        if u.paused:
            plan.warnings.append(
                f"{u.name}: paused — secrets refreshed, excluded from USERS")

    if errors:
        raise SyncError("; ".join(errors))

    # Users deleted locally: their per-user secrets are orphans. Delete.
    for name in sorted(remote_names):
        m = PER_USER_RE.match(name)
        if m and m.group(2).casefold() not in local:
            plan.actions.append(DeleteSecret(name))

    plan.actions.append(SetVariable(
        "USERS", json.dumps(sorted(u.name for u in users if not u.paused))))

    kept = sum(1 for a in plan.actions if isinstance(a, SetSecret))
    if len(remote_names) + kept > SECRET_CAP_SOFT:
        plan.warnings.append(
            f"{len(remote_names) + kept} repo secrets after sync — GitHub caps "
            f"at 100; consider consolidating per-user SMTP into one JSON secret")
    return plan


def _gh(argv: list[str], input_bytes: bytes | None = None,
        repo: str | None = None) -> str:
    """Run one gh command; return stdout. Values go in via stdin only."""
    full = ["gh", *argv]
    if repo:
        full += ["--repo", repo]
    proc = subprocess.run(full, input=input_bytes, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(argv)} failed: {proc.stderr.decode(errors='replace')[:300]}")
    return proc.stdout.decode(errors="replace")


def remote_secret_names(repo: str | None = None) -> set[str]:
    out = _gh(["secret", "list", "--json", "name"], repo=repo)
    return {s["name"] for s in json.loads(out or "[]")}


def apply_plan(plan: Plan, repo: str | None = None,
               runner=_gh) -> list[str]:
    """Execute the plan. Returns human-readable action log lines (names only)."""
    log: list[str] = []
    for action in plan.actions:
        if isinstance(action, SetSecret):
            runner(["secret", "set", action.name], input_bytes=action.value,
                   repo=repo)
            log.append(f"set secret {action.name} ({len(action.value)} bytes)")
        elif isinstance(action, DeleteSecret):
            runner(["secret", "delete", action.name], repo=repo)
            log.append(f"deleted secret {action.name}")
        elif isinstance(action, SetVariable):
            runner(["variable", "set", action.name, "--body", action.value],
                   repo=repo)
            log.append(f"set variable {action.name}={action.value}")
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (names + sizes only), change nothing")
    ap.add_argument("--yes", action="store_true",
                    help="apply without the interactive confirmation")
    ap.add_argument("--repo", help="target repo (default: gh's default repo)")
    args = ap.parse_args(argv)

    _gh(["auth", "status"], repo=None)  # fail fast with gh's own message

    users, warnings = discover_users(ROOT / "users")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not users:
        print("no local users found — nothing to sync", file=sys.stderr)
        return 1

    remote = remote_secret_names(args.repo)
    try:
        plan = build_plan(users, ROOT / "users", remote)
    except SyncError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in plan.warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.dry_run:
        for line in _describe(plan):
            print(line)
        print(f"{len(plan.actions)} actions planned — dry run, nothing changed")
        return 0

    if not args.yes:
        for line in _describe(plan):
            print(line)
        if not sys.stdin.isatty() or input("proceed? [y/N] ").strip().lower() != "y":
            print("aborted", file=sys.stderr)
            return 1

    for line in apply_plan(plan, args.repo):
        print(line)
    return 0


def _describe(plan: Plan) -> list[str]:
    lines = []
    for action in plan.actions:
        if isinstance(action, SetSecret):
            lines.append(f"set secret {action.name} ({len(action.value)} bytes)")
        elif isinstance(action, DeleteSecret):
            lines.append(f"delete secret {action.name}")
        elif isinstance(action, SetVariable):
            lines.append(f"set variable {action.name}={action.value}")
    return lines


if __name__ == "__main__":
    sys.exit(main())
