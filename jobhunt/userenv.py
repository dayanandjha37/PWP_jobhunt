"""Per-user env files for multi-user runs.

`run-all` sweeps users sequentially in one process, so user 1's credentials
must never leak into user 2's run. `env_scope` OVERRIDES os.environ (never
setdefault, unlike the root `.env` loader) and restores the previous values
on exit — including removing keys the user file introduced.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse a KEY=VALUE file into a dict. Same syntax as the root .env
    loader (comments with #, optional surrounding quotes). Missing file
    returns {} — a user may legitimately have no secrets on this machine."""
    p = Path(path)
    if not p.exists():
        return {}
    env: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


@contextmanager
def env_scope(env: dict[str, str]):
    """Temporarily apply `env` to os.environ, then restore exactly what was
    there before. Keys the file did not mention are left untouched."""
    saved: dict[str, str | None] = {}
    try:
        for k, v in env.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
