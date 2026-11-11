"""PMD 7 integration (BSD-style licence): CPD duplication and Java design rules.

PMD is optional. It is located through ``CODEHEALTH_PMD_HOME`` (a PMD
``pmd-bin-*`` directory, or a directory holding one) or, when that variable is
unset, under the per-user data directory where ``codehealth install-pmd``
puts it (see :mod:`codehealth.pmd_install`).
``CODEHEALTH_NO_PMD=1`` turns it off. When PMD or Java is missing every
caller degrades: PMD-backed smells are reported as unavailable, never as
errors.

PMD runs as a subprocess with an argument list (no shell), a timeout and
``--no-progress``; it only ever reads copies of the analysed content that we
write into a private scratch directory under the cache directory, so it never
follows paths or symlinks inside the analysed repository. Reports are parsed
with ``defusedxml`` (CPD XML) and ``json`` (PMD JSON).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from defusedxml import DefusedXmlException, ElementTree

from .pmd_install import default_install_dir

DEFAULT_TIMEOUT = 120.0

# Our language name -> CPD language id. TSX goes through the TypeScript lexer.
CPD_LANGUAGES: dict[str, str] = {
    "python": "python",
    "javascript": "ecmascript",
    "typescript": "typescript",
    "tsx": "typescript",
    "java": "java",
    "go": "go",
    "cpp": "cpp",
    "csharp": "cs",
    "objectivec": "objectivec",
    "ruby": "ruby",
    "kotlin": "kotlin",
    "swift": "swift",
    "scala": "scala",
    "php": "php",
    "dart": "dart",
    "lua": "lua",
    "fortran": "fortran",
    "perl": "perl",
    "plsql": "plsql",
    "rust": "rust",
}

JAVA_RULES = (
    "category/java/design.xml/GodClass",
    "category/java/design.xml/TooManyMethods",
    "category/java/design.xml/ExcessiveParameterList",
    "category/java/design.xml/CognitiveComplexity",
    "category/java/design.xml/NPathComplexity",
    "category/java/design.xml/DataClass",
)

_GOD_CLASS = re.compile(r"WMC=(\d+).*?ATFD=(\d+).*?TCC=([\d.]+)%")


class PmdError(RuntimeError):
    """PMD could not run or produced an unreadable report."""


@dataclass(frozen=True)
class PmdInstall:
    home: Path
    executable: Path
    version: str
    java: str


@dataclass(frozen=True)
class Occurrence:
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Duplication:
    lines: int
    tokens: int
    occurrences: tuple[Occurrence, ...]


@dataclass(frozen=True)
class Violation:
    rule: str
    begin_line: int
    end_line: int
    message: str
    priority: int
    path: str = ""  # file PMD reported it for (a scratch copy)

    def to_dict(self) -> dict:
        return {"rule": self.rule, "line": self.begin_line, "end_line": self.end_line, "message": self.message}


# ----- locating --------------------------------------------------------------------
def _candidate_homes() -> list[Path]:
    base = default_install_dir()
    if (base / "bin" / "pmd").is_file():
        return [base]
    return sorted((p for p in base.glob("pmd-bin-*") if (p / "bin" / "pmd").is_file()), reverse=True)


def _version_of(home: Path) -> str:
    jars = sorted(home.glob("lib/pmd-core-*.jar"))
    if jars:
        return jars[-1].stem.removeprefix("pmd-core-")
    return home.name.removeprefix("pmd-bin-")


def _java() -> str | None:
    java_home = os.environ.get("JAVA_HOME")
    if java_home and (Path(java_home) / "bin" / "java").is_file():
        return str(Path(java_home) / "bin" / "java")
    return shutil.which("java")


def locate() -> tuple[PmdInstall | None, str | None]:
    """Return the PMD installation, or None and the reason it is unavailable."""
    if os.environ.get("CODEHEALTH_NO_PMD", "").strip() not in ("", "0"):
        return None, "disabled by CODEHEALTH_NO_PMD"
    homes = _candidate_homes()
    if not homes:
        return None, "PMD not found; run `codehealth install-pmd` or set CODEHEALTH_PMD_HOME"
    java = _java()
    if java is None:
        return None, "Java runtime not found (PMD needs Java 8+; set JAVA_HOME or put java on PATH)"
    home = homes[0]
    return PmdInstall(home=home, executable=home / "bin" / "pmd", version=_version_of(home), java=java), None


def status() -> dict:
    install, reason = locate()
    if install is None:
        return {"available": False, "reason": reason}
    return {"available": True, "version": install.version}


# ----- scratch space -------------------------------------------------------------------
def cache_dir() -> Path:
    configured = os.environ.get("CODEHEALTH_CACHE_DIR")
    if configured:
        base = Path(configured)
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".cache") / "codehealth"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    return base


@contextlib.contextmanager
def scratch_dir() -> Iterator[Path]:
    """A private (0700) working directory under the cache directory, removed afterwards."""
    work_root = cache_dir() / "work"
    work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path(tempfile.mkdtemp(prefix="run-", dir=work_root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def safe_relpath(relpath: str) -> Path:
    """Validate a repository-relative path before recreating it in scratch space."""
    path = Path(relpath)
    if _is_unsafe_path(path):
        raise ValueError(f"unsafe relative path: {relpath!r}")
    return path


def _is_unsafe_path(path: Path) -> bool:
    """Absolute, empty, or with ``.``/``..``/empty components."""
    return path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts)


def write_sources(root: Path, files: dict[str, str]) -> dict[Path, str]:
    """Write ``{relpath: text}`` below ``root``; return {written path: relpath}."""
    written: dict[Path, str] = {}
    for relpath, text in files.items():
        target = root / safe_relpath(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written[target.resolve()] = relpath
    return written


# ----- running ----------------------------------------------------------------------------
FILES_PER_TIMEOUT = 100  # a batch gets one more timeout period per this many files


def _timeout(files: int = 1) -> float:
    try:
        base = float(os.environ.get("CODEHEALTH_PMD_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        base = DEFAULT_TIMEOUT
    return base * (1 + max(files - 1, 0) // FILES_PER_TIMEOUT)


def _run(install: PmdInstall, args: list[str], files: int = 1) -> str:
    env = dict(os.environ)
    env.setdefault("JAVA_HOME", str(Path(install.java).resolve().parent.parent))
    try:
        proc = subprocess.run(
            [str(install.executable), *args],
            capture_output=True,
            text=True,
            timeout=_timeout(files),
            stdin=subprocess.DEVNULL,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PmdError(f"PMD did not run: {type(exc).__name__}") from exc
    if proc.returncode not in (0, 4, 5):  # 4: violations found, 5: recoverable errors
        last = (proc.stderr.strip().splitlines() or ["no output"])[-1][:200]
        raise PmdError(f"PMD exited with status {proc.returncode}: {last}")
    return proc.stdout


def _file_count(directory: Path) -> int:
    return sum(1 for p in directory.rglob("*") if p.is_file())


def run_cpd(install: PmdInstall, directory: Path, language: str, min_tokens: int) -> list[Duplication]:
    """Run CPD over ``directory`` for one of our language names (timeout scaled by its file count)."""
    cpd_language = CPD_LANGUAGES[language]
    args = [
        "cpd",
        "--format", "xml",
        "--minimum-tokens", str(int(min_tokens)),
        "--language", cpd_language,
        "--ignore-identifiers",
        "--ignore-literals",
        "--no-fail-on-violation",
        "--no-fail-on-error",
        "--encoding", "UTF-8",
        "--dir", str(directory),
    ]
    return parse_cpd_xml(_run(install, args, _file_count(directory)))


def run_java_rules(install: PmdInstall, directory: Path) -> list[Violation]:
    pmd_cache = cache_dir() / "pmd"
    pmd_cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = [
        "check",
        "--no-progress",
        "--no-fail-on-violation",
        "--no-fail-on-error",
        "--format", "json",
        "--rulesets", ",".join(JAVA_RULES),
        "--cache", str(pmd_cache / "java-design.cache"),
        "--encoding", "UTF-8",
        "--dir", str(directory),
    ]
    return parse_pmd_json(_run(install, args, _file_count(directory)))


# ----- parsing ------------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_cpd_xml(text: str) -> list[Duplication]:
    """Parse a CPD XML report (PMD 7 namespaced or older plain format)."""
    start = text.find("<")
    if start < 0:
        return []
    try:
        root = ElementTree.fromstring(text[start:])
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise PmdError("unreadable CPD report") from exc
    found = []
    for dup in root:
        if _local(dup.tag) != "duplication":
            continue
        occurrences = tuple(
            Occurrence(
                path=f.get("path", ""),
                start_line=int(f.get("line", "0")),
                end_line=int(f.get("endline") or (int(f.get("line", "0")) + int(dup.get("lines", "1")) - 1)),
            )
            for f in dup
            if _local(f.tag) == "file"
        )
        found.append(Duplication(int(dup.get("lines", "0")), int(dup.get("tokens", "0")), occurrences))
    return found


def parse_pmd_json(text: str) -> list[Violation]:
    try:
        data = json.loads(text[text.find("{"):] if "{" in text else "{}")
    except json.JSONDecodeError as exc:
        raise PmdError("unreadable PMD report") from exc
    return [
        Violation(
            rule=str(v.get("rule", "")),
            begin_line=int(v.get("beginline", 0)),
            end_line=int(v.get("endline", v.get("beginline", 0))),
            message=str(v.get("description", ""))[:300],
            priority=int(v.get("priority", 3)),
            path=str(f.get("filename", "")),
        )
        for f in data.get("files", [])
        for v in f.get("violations", [])
    ]


def god_class_metrics(message: str) -> dict | None:
    """WMC, ATFD and TCC from a GodClass message."""
    match = _GOD_CLASS.search(message)
    if match is None:
        return None
    return {"wmc": int(match.group(1)), "atfd": int(match.group(2)), "tcc_percent": float(match.group(3))}
