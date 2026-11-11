from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codehealth import pmd

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    install, reason = pmd.locate()
    if install is not None:
        return
    skip = pytest.mark.skip(reason=f"PMD unavailable: {reason}")
    for item in items:
        if "pmd" in item.keywords:
            item.add_marker(skip)


def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path
