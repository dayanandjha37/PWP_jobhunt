"""users_sync: local users/ -> GitHub secrets plan. Offline — gh is faked."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

from users_sync import (DeleteSecret, SetSecret, SetVariable, SyncError,
                        UserSpec, apply_plan, build_plan, discover_users)


def make_user(root: Path, name: str, env: str = "", paused: bool = False,
              profile: str | None = '{"name": "x"}',
              config: str = "filters: {}\n") -> None:
    d = root / "users" / name
    d.mkdir(parents=True)
    if profile is not None:
        (d / "profile.json").write_text(profile, encoding="utf-8")
    if config is not None:
        (d / "config.yaml").write_text(config, encoding="utf-8")
    if env:
        (d / ".env").write_text(env, encoding="utf-8")
    if paused:
        (d / ".paused").write_text("", encoding="utf-8")


DAYANAND_ENV = (
    "LLM_PROVIDER=openai-compatible\n"
    "SMTP_HOST=smtp.gmail.com\n"
    "SMTP_PORT=587\n"
    "SMTP_USER=dayanand@example.com\n"
    "SMTP_PASS=apppassword\n"
    "MAIL_TO=dayanand@example.com\n"
)


# --- discover_users ---------------------------------------------------------

def test_discover_excludes_sample_and_flags_paused(tmp_path):
    make_user(tmp_path, "dayanand")
    make_user(tmp_path, "piyush", paused=True)
    make_user(tmp_path, "sample")
    users, warnings = discover_users(tmp_path / "users")
    assert [(u.name, u.paused) for u in users] == \
        [("dayanand", False), ("piyush", True)]
    assert warnings == []


def test_discover_warns_on_bad_charset_names(tmp_path):
    make_user(tmp_path, "good")
    make_user(tmp_path, "bad-name")  # hyphen: no GitHub secret name possible
    users, warnings = discover_users(tmp_path / "users")
    assert [u.name for u in users] == ["good"]
    assert len(warnings) == 1 and "bad-name" in warnings[0]


def test_discover_empty_dir(tmp_path):
    users, warnings = discover_users(tmp_path / "users")
    assert users == [] and warnings == []


# --- build_plan -------------------------------------------------------------

def test_build_plan_happy_path_and_missing_smtp_pass(tmp_path):
    make_user(tmp_path, "dayanand", env=DAYANAND_ENV)
    make_user(tmp_path, "piyush", env="SMTP_USER=piyush@example.com\nMAIL_TO=p@example.com\n")
    plan = build_plan(*_ctx(tmp_path), remote_names=set())

    sets = {a.name: a for a in plan.actions if isinstance(a, SetSecret)}
    assert sets["PROFILE_JSON_DAYANAND"].value == b'{"name": "x"}'
    assert sets["CONFIG_YAML_DAYANAND"].value == b"filters: {}\n"
    assert sets["SMTP_USER_DAYANAND"].value == b"dayanand@example.com"
    assert sets["SMTP_PASS_DAYANAND"].value == b"apppassword"
    assert sets["SMTP_USER_PIYUSH"].value == b"piyush@example.com"
    assert "SMTP_PASS_PIYUSH" not in sets          # never set an absent key
    assert any("SMTP_PASS" in w and "piyush" in w for w in plan.warnings)
    var = _users_var(plan)
    assert var.value == json.dumps(["dayanand", "piyush"])


def test_build_plan_skips_empty_env_values(tmp_path):
    make_user(tmp_path, "solo", env="SMTP_HOST=\nSMTP_USER=\nMAIL_TO=x@example.com\n")
    plan = build_plan(*_ctx(tmp_path), remote_names=set())
    sets = {a.name for a in plan.actions if isinstance(a, SetSecret)}
    assert "SMTP_HOST_SOLO" not in sets             # empty value: not set
    assert "SMTP_USER_SOLO" not in sets
    assert "MAIL_TO_SOLO" in sets


def test_build_plan_missing_or_broken_profile_aborts(tmp_path):
    make_user(tmp_path, "broken", profile=None)
    make_user(tmp_path, "invalid", profile="{not json")
    with pytest.raises(SyncError) as e:
        build_plan(*_ctx(tmp_path), remote_names=set())
    assert "broken" in str(e.value) and "invalid" in str(e.value)


def test_build_plan_missing_config_aborts(tmp_path):
    make_user(tmp_path, "noconf", config=None)
    with pytest.raises(SyncError) as e:
        build_plan(*_ctx(tmp_path), remote_names=set())
    assert "noconf" in str(e.value)


def test_build_plan_deletes_orphan_secrets_for_deleted_users(tmp_path):
    make_user(tmp_path, "dayanand", env=DAYANAND_ENV)
    remote = {"SMTP_PASS_GONE", "PROFILE_JSON_GONE", "PROFILE_JSON_DAYANAND",
              "LLM_API_KEY", "UNRELATED"}
    plan = build_plan(*_ctx(tmp_path), remote_names=remote)
    deletes = {a.name for a in plan.actions if isinstance(a, DeleteSecret)}
    assert deletes == {"SMTP_PASS_GONE", "PROFILE_JSON_GONE"}
    sets = {a.name for a in plan.actions if isinstance(a, SetSecret)}
    assert "PROFILE_JSON_DAYANAND" in sets           # existing user refreshed


def test_build_plan_paused_user_keeps_secrets_but_leaves_users_var(tmp_path):
    make_user(tmp_path, "dayanand", env=DAYANAND_ENV)
    make_user(tmp_path, "piyush", env=DAYANAND_ENV, paused=True)
    plan = build_plan(*_ctx(tmp_path), remote_names=set())
    sets = {a.name for a in plan.actions if isinstance(a, SetSecret)}
    assert "PROFILE_JSON_PIYUSH" in sets             # secrets refreshed
    assert _users_var(plan).value == json.dumps(["dayanand"])
    assert any("piyush" in w and "paused" in w for w in plan.warnings)


def test_build_plan_warns_on_local_llm_keys(tmp_path):
    make_user(tmp_path, "keyed", env="LLM_API_KEY=sk-not-synced\nSMTP_USER=k@example.com\n")
    plan = build_plan(*_ctx(tmp_path), remote_names=set())
    assert any("LLM" in w for w in plan.warnings)
    sets = {a.name for a in plan.actions if isinstance(a, SetSecret)}
    assert "LLM_API_KEY_KEYED" not in sets           # LLM keys never synced


def _ctx(tmp_path: Path):
    users, _ = discover_users(tmp_path / "users")
    return users, tmp_path / "users"


def _users_var(plan) -> SetVariable:
    vars_ = [a for a in plan.actions if isinstance(a, SetVariable)]
    assert len(vars_) == 1
    return vars_[0]


# --- apply_plan -------------------------------------------------------------

class FakeGh:
    def __init__(self):
        self.calls = []  # (argv tuple, input bytes)

    def __call__(self, argv, input_bytes=None, repo=None):
        full = tuple(argv) + (("--repo", repo) if repo else ())
        self.calls.append((full, input_bytes))
        return "[]"


def test_apply_plan_values_travel_via_stdin_never_argv(tmp_path):
    make_user(tmp_path, "dayanand", env=DAYANAND_ENV)
    plan = build_plan(*_ctx(tmp_path), remote_names={"SMTP_PASS_GONE"})

    fake = FakeGh()
    log = apply_plan(plan, repo=None, runner=fake)

    secret_sets = [c for c in fake.calls if c[0][:2] == ("secret", "set")]
    assert secret_sets, "expected secret sets"
    for argv, input_bytes in secret_sets:
        assert input_bytes is not None              # value in stdin
        assert all(b"apppassword" != part.encode() for part in argv)
    assert any(c[0] == ("secret", "delete", "SMTP_PASS_GONE") for c in fake.calls)
    var_calls = [c for c in fake.calls if c[0][:2] == ("variable", "set")]
    assert var_calls[0][0] == ("variable", "set", "USERS", "--body",
                               '["dayanand"]')
    assert any("SMTP_PASS_GONE" in line for line in log)


# --- local run-all pause semantics (cli._user_dirs) -------------------------

def test_user_dirs_skips_paused_unless_named(tmp_path):
    import importlib
    cli = importlib.import_module("jobhunt.cli")
    for name in ("dayanand", "piyush", "sample"):
        (tmp_path / "users" / name).mkdir(parents=True)
    (tmp_path / "users" / "piyush" / ".paused").write_text("", encoding="utf-8")
    (tmp_path / "users" / "loose-file").write_text("not a dir", encoding="utf-8")

    got = [d.name for d in cli._user_dirs(tmp_path / "users")]
    assert got == ["dayanand"]    # piyush paused, sample scaffold, loose file

    # an explicit --user overrides the pause
    got = [d.name for d in cli._user_dirs(tmp_path / "users", "piyush")]
    assert got == ["piyush"]
