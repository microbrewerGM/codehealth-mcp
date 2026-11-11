"""codehealth install-pmd: pinned download, checksum, safe unpacking (no network in these tests)."""

from __future__ import annotations

import hashlib
import io
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from codehealth import cli, pmd_install
from codehealth.analysis import review_file

from .conftest import FIXTURES


def _zip(entries: dict[str, tuple[str, int]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, (text, mode) in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, text)
    return buf.getvalue()


def _fake_download(payload: bytes):
    def download(url: str, dest: Path) -> str:
        assert url.startswith("https://github.com/pmd/pmd/releases/download/")
        dest.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    return download


GOOD = _zip({
    f"pmd-bin-{pmd_install.PMD_VERSION}/bin/pmd": ("#!/bin/sh\nexit 0\n", 0o755),
    f"pmd-bin-{pmd_install.PMD_VERSION}/LICENSE": ("license", 0o644),
})


def test_installs_with_matching_checksum_and_keeps_exec_bit(monkeypatch, tmp_path):
    monkeypatch.setattr(pmd_install, "_download", _fake_download(GOOD))
    home = pmd_install.install(tmp_path, sha256=hashlib.sha256(GOOD).hexdigest())
    assert home == tmp_path.resolve() / f"pmd-bin-{pmd_install.PMD_VERSION}"
    assert (home / "bin" / "pmd").stat().st_mode & stat.S_IXUSR
    assert [p.name for p in tmp_path.iterdir()] == [home.name]  # download dir removed
    assert pmd_install.install(tmp_path) == home  # idempotent, no second download


def test_checksum_mismatch_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(pmd_install, "_download", _fake_download(GOOD))
    with pytest.raises(pmd_install.InstallError, match="SHA-256 mismatch"):
        pmd_install.install(tmp_path)  # pinned digest of the real release
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", ["../evil", "/abs/evil", "pmd-bin-x/../../evil"])
def test_unsafe_archive_paths_are_refused(monkeypatch, tmp_path, bad):
    payload = _zip({bad: ("x", 0o644)})
    monkeypatch.setattr(pmd_install, "_download", _fake_download(payload))
    with pytest.raises(pmd_install.InstallError, match="unsafe"):
        pmd_install.install(tmp_path / "pmd", sha256=hashlib.sha256(payload).hexdigest())
    assert not (tmp_path / "evil").exists()


def test_non_https_url_is_refused(tmp_path):
    with pytest.raises(pmd_install.InstallError, match="non-HTTPS"):
        pmd_install._download("http://example.invalid/pmd.zip", tmp_path / "x.zip")


def test_default_dir_respects_env_and_user_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEHEALTH_PMD_HOME", str(tmp_path / "custom"))
    assert pmd_install.default_install_dir() == tmp_path / "custom"
    monkeypatch.delenv("CODEHEALTH_PMD_HOME")
    default = pmd_install.default_install_dir()
    assert default.name == "pmd" and default.parent.name == "codehealth-mcp"


def test_existing_pmd_home_is_reused(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pmd").write_text("#!/bin/sh\n")
    assert pmd_install.install(tmp_path) == tmp_path.resolve()


def test_cli_install_pmd(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pmd_install, "PMD_SHA256", hashlib.sha256(GOOD).hexdigest())
    monkeypatch.setattr(pmd_install.install, "__kwdefaults__", {"url": pmd_install.PMD_URL, "sha256": pmd_install.PMD_SHA256})
    monkeypatch.setattr(pmd_install, "_download", _fake_download(GOOD))
    assert cli.main(["install-pmd", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert f"CODEHEALTH_PMD_HOME={tmp_path.resolve() / ('pmd-bin-' + pmd_install.PMD_VERSION)}" in out
    shutil.rmtree(tmp_path / f"pmd-bin-{pmd_install.PMD_VERSION}")


def test_lizard_extensions_report_what_ran(monkeypatch):
    """Adapter languages get nesting from tree-sitter, so lizard's nd pass does not run."""
    monkeypatch.setenv("CODEHEALTH_NO_PMD", "1")
    python = review_file(FIXTURES / "python" / "smelly.py").analyzers["lizard"]["extensions"]
    assert python == ["cognitive"]
    csharp = review_file(FIXTURES / "csharp" / "Smelly.cs").analyzers["lizard"]["extensions"]
    assert csharp == ["nd", "cognitive"]
