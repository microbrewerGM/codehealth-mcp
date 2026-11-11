"""Read-only git plumbing for untrusted repositories.

Only object-database and index reads are used (ls-tree, ls-files -s,
cat-file, diff-tree between two trees, merge-base). Nothing here asks git
to read or refresh the working tree, so repository-local clean/smudge
filters, fsmonitor hooks, textconv drivers and external diff tools never
run. Working-tree changes are detected by hashing file bytes in Python in
git's blob format. Every path list is NUL-separated (``-z``).
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_HARDENING: tuple[str, ...] = (
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "diff.external=",
    "-c", "core.pager=cat",
    "--no-pager",
    "--no-optional-locks",
)
DIFF_SAFETY: tuple[str, ...] = ("--no-ext-diff", "--no-textconv")
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"


# Hard ceiling on bytes read from an untrusted repository. The rules file's
# file_max_bytes (default 2 MB) is enforced later by the analyzer; this guard
# stops a huge blob or file from being loaded into memory at all.
MAX_READ_BYTES = 16 * 1024 * 1024


class GitError(RuntimeError):
    pass


class ContentTooLargeError(ValueError):
    """A blob or working-tree file is larger than MAX_READ_BYTES."""

    def __init__(self, what: str, size: int | None = None):
        shown = f"{size} bytes" if size is not None else f"over {MAX_READ_BYTES} bytes"
        super().__init__(f"{what[:120]} is too large to analyze ({shown}; limit {MAX_READ_BYTES} bytes)")


@dataclass(frozen=True)
class Change:
    """One changed path between two trees; ``old_path`` differs on renames."""

    status: str
    old_path: str | None
    new_path: str | None


def git_command(repo: Path, *args: str) -> list[str]:
    return ["git", *GIT_HARDENING, "-C", str(repo), *args]


def run(repo: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        git_command(repo, *args),
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
        env={**os.environ, **GIT_ENV},
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {args[0] if args else ''} failed: {stderr[:200]}")
    return result.stdout if result.returncode == 0 else b""


def check_ref(ref: str) -> str:
    """Reject refs that git would parse as options."""
    if _is_unsafe_ref(ref):
        raise GitError(f"invalid git ref: {ref[:80]!r}")
    return ref


def _is_unsafe_ref(ref: str) -> bool:
    """Empty, option-like (``-x``) or containing NUL."""
    return not ref or ref.startswith("-") or "\0" in ref


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def _records(raw: bytes) -> list[str]:
    return [_decode(r) for r in raw.split(b"\0") if r]


# ----- repository facts --------------------------------------------------------
def repo_root(path: Path) -> Path:
    start = path if path.is_dir() else path.parent
    return Path(_decode(run(start, "rev-parse", "--show-toplevel")).rstrip("\n"))


def has_head(repo: Path) -> bool:
    return bool(run(repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False).strip())


def object_format(repo: Path) -> str:
    fmt = _decode(run(repo, "rev-parse", "--show-object-format", check=False)).strip()
    return fmt or "sha1"


def merge_base(repo: Path, base_ref: str) -> str:
    return _decode(run(repo, "merge-base", "HEAD", check_ref(base_ref))).strip()


def blob_oid(data: bytes, fmt: str = "sha1") -> str:
    """Object id git would give ``data`` as a blob (no filters applied)."""
    digest = hashlib.new("sha256" if fmt == "sha256" else "sha1")
    digest.update(b"blob %d\0" % len(data))
    digest.update(data)
    return digest.hexdigest()


# ----- listings -------------------------------------------------------------------
def tree_entries(repo: Path, rev: str) -> dict[str, str]:
    """Regular-file blobs of ``rev`` as {path: oid}; symlinks and submodules are skipped."""
    entries: dict[str, str] = {}
    for record in _records(run(repo, "ls-tree", "-r", "-z", "--full-tree", check_ref(rev))):
        meta, _, path = record.partition("\t")
        mode, kind, oid = meta.split(" ")
        if kind == "blob" and mode not in (SYMLINK_MODE, GITLINK_MODE):
            entries[path] = oid
    return entries


def index_entries(repo: Path) -> dict[str, str]:
    """Stage-0 regular files in the index as {path: oid}."""
    entries: dict[str, str] = {}
    for record in _records(run(repo, "ls-files", "-s", "-z")):
        meta, _, path = record.partition("\t")
        mode, oid, stage = meta.split(" ")
        if stage == "0" and mode not in (SYMLINK_MODE, GITLINK_MODE):
            entries[path] = oid
    return entries


def tree_changes(repo: Path, old_rev: str, new_rev: str) -> list[Change]:
    """Tree-to-tree changes with rename detection (no working tree involved)."""
    raw = run(repo, "diff-tree", *DIFF_SAFETY, "-r", "-z", "-M", "--name-status", check_ref(old_rev), check_ref(new_rev))
    return _parse_name_status(_records(raw))


def _parse_name_status(fields: list[str]) -> list[Change]:
    changes: list[Change] = []
    i = 0
    while i < len(fields):
        status = fields[i][0]
        if status in ("R", "C"):
            changes.append(Change(status, fields[i + 1], fields[i + 2]))
            i += 3
            continue
        path = fields[i + 1]
        changes.append(Change(status, None if status == "A" else path, None if status == "D" else path))
        i += 2
    return changes


# ----- contents ----------------------------------------------------------------------
def read_blob(repo: Path, oid: str) -> bytes:
    """Raw blob bytes; ``cat-file blob`` applies no filters or textconv. Size-checked first."""
    oid = check_ref(oid)
    size = int(run(repo, "cat-file", "-s", oid).strip() or b"0")
    if size > MAX_READ_BYTES:
        raise ContentTooLargeError(f"blob {oid}", size)
    return run(repo, "cat-file", "blob", oid)


def read_worktree(repo: Path, relpath: str) -> bytes | None:
    """Bytes of a regular file inside ``repo``; None when missing or reached through a symlink."""
    if not _is_plain_relpath(relpath):
        return None
    target = _regular_file(repo, Path(relpath).parts)
    if target is None:
        return None
    with open(target, "rb") as handle:  # bounded read: the file may grow after any size check
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise ContentTooLargeError(relpath)
    return data


def worktree_oid(repo: Path, relpath: str, fmt: str = "sha1") -> str | None:
    """Blob id of a working-tree file, hashed in chunks so any size uses bounded memory."""
    if not _is_plain_relpath(relpath):
        return None
    target = _regular_file(repo, Path(relpath).parts)
    if target is None:
        return None
    digest = hashlib.new("sha256" if fmt == "sha256" else "sha1")
    with open(target, "rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        digest.update(b"blob %d\0" % size)
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_plain_relpath(relpath: str) -> bool:
    """Relative, non-empty, and free of ``.``, ``..``, empty and ``.git`` components."""
    path = Path(relpath)
    return bool(path.parts) and not path.is_absolute() and not any(p in ("", ".", "..", ".git") for p in path.parts)


def _regular_file(repo: Path, parts: tuple[str, ...]) -> Path | None:
    """Walk ``parts`` below ``repo`` with lstat; None on a missing part, any symlink, or a non-regular file."""
    current, mode = repo, 0
    for part in parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(mode):
            return None
    return current if stat.S_ISREG(mode) else None
