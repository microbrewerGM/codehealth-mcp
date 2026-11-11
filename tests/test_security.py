"""Security regressions: glob ReDoS, symlinked rules files, hostile git config."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from codehealth import config, delta, gitrepo, globmatch

from .conftest import git


# ----- glob matching ---------------------------------------------------------
def test_pathological_globs_are_fast():
    pattern = "*a" * 15 + "*b"
    start = time.perf_counter()
    assert not globmatch.glob_match(pattern, "a" * 5000)
    assert not globmatch.glob_match("/".join(["**"] * 150) + "/x", "/".join(["d"] * 300))
    assert time.perf_counter() - start < 1.0


def test_glob_normalization_collapses_runs():
    assert globmatch.normalize("**/**/**/src/***.py") == ("**", "src", "*.py")
    assert globmatch.glob_match("**/**/src/***.py", "a/b/src/x.py")


def test_glob_limits_are_enforced():
    with pytest.raises(globmatch.GlobError):
        globmatch.normalize("a" * 513)
    with pytest.raises(globmatch.GlobError):
        globmatch.normalize("/".join(["*x"] * 33))
    errors = config.validate_config({"rule_sets": [{"matching_content_path": "?" * 40}]})
    assert errors and "wildcards" in errors[0]


def test_glob_question_mark_and_no_slash_crossing():
    assert globmatch.glob_match("src/?.py", "src/a.py")
    assert not globmatch.glob_match("src/?.py", "src/ab.py")
    assert not globmatch.glob_match("*.py", "src/a.py")


# ----- rules file writer -------------------------------------------------------
def test_symlinked_config_dir_is_refused(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (repo / ".codehealth").symlink_to(outside, target_is_directory=True)
    with pytest.raises(config.ConfigError, match="symlink|outside"):
        config.set_rule(repo, "Large Method", 0)
    assert list(outside.iterdir()) == []


def test_symlinked_rules_file_is_refused(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "victim.json"
    outside.write_text(json.dumps({"rule_sets": []}))
    (repo / ".codehealth").mkdir()
    (repo / ".codehealth" / "rules.json").symlink_to(outside)
    with pytest.raises(config.ConfigError, match="symlink|outside"):
        config.set_rule(repo, "Large Method", 0)
    assert json.loads(outside.read_text()) == {"rule_sets": []}


def test_symlink_inside_repo_is_also_refused(repo):
    real = repo / "real"
    real.mkdir()
    (repo / ".codehealth").symlink_to(real, target_is_directory=True)
    with pytest.raises(config.ConfigError, match="symlink"):
        config.set_rule(repo, "Large Method", 0)


def test_non_json_or_outside_target_is_refused(repo, tmp_path_factory):
    with pytest.raises(config.ConfigError):
        config.safe_config_target(repo, repo / "rules.txt")
    with pytest.raises(config.ConfigError):
        config.safe_config_target(repo, tmp_path_factory.mktemp("x") / "rules.json")


def test_write_is_atomic_and_leaves_no_temp_files(repo):
    path = config.set_rule(repo, "Large Method", 0)
    config.set_threshold(repo, "function_max_arguments", 6)
    assert sorted(p.name for p in path.parent.iterdir()) == ["rules.json"]
    assert json.loads(path.read_text())["rule_sets"][0]["thresholds"][0]["value"] == 6


# ----- git hardening ---------------------------------------------------------------
def test_hardening_flags_and_env_are_used():
    cmd = gitrepo.git_command(Path("/repo"), "ls-files")
    for flag in (
        "core.fsmonitor=false",
        "core.hooksPath=/dev/null",
        "diff.external=",
        "core.pager=cat",
        "--no-pager",
        "--no-optional-locks",
    ):
        assert flag in cmd
    assert cmd.index("--no-pager") < cmd.index("-C")
    assert gitrepo.GIT_ENV == {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    assert set(gitrepo.DIFF_SAFETY) == {"--no-ext-diff", "--no-textconv"}


def _hostile_repo(repo: Path) -> Path:
    marker = repo.parent / f"{repo.name}-pwned"
    hook = repo.parent / f"{repo.name}-hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    hook.chmod(0o755)
    (repo / "a.py").write_text("def f(a):\n    return a\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "config", "core.fsmonitor", str(hook))
    git(repo, "config", "diff.external", str(hook))
    (repo / "a.py").write_text("def f(a, b):\n    return a\n")
    return marker


def test_hostile_git_config_never_runs(repo):
    marker = _hostile_repo(repo)
    delta.pre_commit_safeguard(repo)
    delta.analyze_change_set(repo, "main")
    delta.file_delta_against_ref(repo, "a.py")
    assert not marker.exists()
    # Sanity check: plain git does run the configured fsmonitor hook.
    subprocess.run(["git", "-C", str(repo), "status"], capture_output=True, check=False, env={**os.environ})
    assert marker.exists()


def test_option_like_refs_are_rejected(repo):
    with pytest.raises(delta.GitError):
        delta.analyze_change_set(repo, "--output=/dev/null")


def test_read_worktree_rejects_traversal(tmp_path):
    from codehealth.gitrepo import read_worktree
    (tmp_path / "repo").mkdir()
    (tmp_path / "secret.py").write_text("x = 1\n")
    repo = tmp_path / "repo"
    for bad in ("../secret.py", "/etc/hosts", ".git/config", "./a.py", ""):
        assert read_worktree(repo, bad) is None
