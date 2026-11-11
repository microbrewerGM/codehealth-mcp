"""``codehealth install-pmd``: download a pinned PMD release and verify it.

PMD is an optional runtime dependency (it needs Java). The archive comes from
the official PMD GitHub release; its SHA-256 is the digest GitHub publishes
for the release asset, and the download is refused if it does not match.
Nothing from the archive is executed here. Archive entries with absolute
paths or ``..`` components are refused before anything is unpacked.

Default install directory: ``$CODEHEALTH_PMD_HOME`` when set, else
``<user data dir>/pmd`` (``~/Library/Application Support/codehealth-mcp/pmd``
on macOS, ``$XDG_DATA_HOME/codehealth-mcp/pmd`` or
``~/.local/share/codehealth-mcp/pmd`` on Linux, ``%LOCALAPPDATA%`` on
Windows). The download and unpacking happen inside that directory, never in
the system temp directory.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from platformdirs import user_data_dir

PMD_VERSION = "7.29.0"
PMD_SHA256 = "d27177c185b837fa57f097e482d1253468aa035379c5eb2671fa0a279109b179"
PMD_URL = (
    f"https://github.com/pmd/pmd/releases/download/pmd_releases/{PMD_VERSION}/pmd-dist-{PMD_VERSION}-bin.zip"
)
APP_NAME = "codehealth-mcp"
CHUNK = 1 << 20


class InstallError(RuntimeError):
    """The archive could not be downloaded, verified or unpacked."""


def default_install_dir() -> Path:
    """``$CODEHEALTH_PMD_HOME`` when set, else the per-user data directory."""
    configured = os.environ.get("CODEHEALTH_PMD_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path(user_data_dir(APP_NAME, appauthor=False)) / "pmd"


def target_dir(install_dir: Path) -> Path:
    return install_dir / f"pmd-bin-{PMD_VERSION}"


def is_installed(install_dir: Path) -> bool:
    return (target_dir(install_dir) / "bin" / "pmd").is_file()


def _download(url: str, dest: Path) -> str:
    """Stream ``url`` to ``dest`` and return the SHA-256 hex digest."""
    if not url.startswith("https://"):
        raise InstallError(f"refusing non-HTTPS URL: {url}")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as out:  # noqa: S310 (https only)
        while chunk := response.read(CHUNK):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _is_unsafe(name: str) -> bool:
    path = PurePosixPath(name)
    return name.startswith(("/", "\\")) or ".." in path.parts or (len(name) > 1 and name[1] == ":")


def _extract(archive: Path, dest: Path) -> None:
    """Unpack ``archive`` into ``dest``, keeping the executable bits of entries."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        bad = [n for n in names if _is_unsafe(n)]
        if bad:
            raise InstallError(f"refusing archive with unsafe paths: {bad[:3]}")
        for info in zf.infolist():
            out = zf.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                os.chmod(out, mode | stat.S_IRUSR)


def install(install_dir: Path | None = None, *, url: str = PMD_URL, sha256: str = PMD_SHA256) -> Path:
    """Install PMD into ``install_dir`` (default :func:`default_install_dir`) and return its home."""
    install_dir = (install_dir or default_install_dir()).expanduser().resolve()
    if (install_dir / "bin" / "pmd").is_file():  # already a PMD home (e.g. CODEHEALTH_PMD_HOME)
        return install_dir
    target = target_dir(install_dir)
    if is_installed(install_dir):
        return target
    install_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".download.", dir=install_dir))
    try:
        archive = work / f"pmd-dist-{PMD_VERSION}-bin.zip"
        actual = _download(url, archive)
        if actual != sha256:
            raise InstallError(f"SHA-256 mismatch for {url}: expected {sha256}, got {actual}")
        _extract(archive, work / "unpacked")
        unpacked = work / "unpacked" / target.name
        if not (unpacked / "bin" / "pmd").is_file():
            raise InstallError(f"archive does not contain {target.name}/bin/pmd")
        if target.exists():
            shutil.rmtree(target)
        unpacked.rename(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return target
