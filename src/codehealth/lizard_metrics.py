"""Per-function metrics from lizard (MIT), run in-process.

lizard is the primary source of the function inventory and of cyclomatic
complexity, NLOC, parameter count, nesting depth (``nd`` extension) and
cognitive complexity (``cognitive`` extension) for every language it reads.
See DESIGN.md ("Analyzers") for where its semantics differ from ours.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lizard_core.extensions import get_extensions
from lizard_core.file_analyzer import FileAnalyzer
from lizard_ext.version import version as _lizard_version
from lizard_languages import languages as _lizard_readers

EXTENSIONS_USED = ("nd", "cognitive")

# lizard's ``nd`` extension closes a nesting level on '}' only. For readers
# whose blocks end without a brace (indentation or ``end`` keywords) it never
# decreases, so sequential ``if`` statements look nested. Its value is used
# only for these brace-delimited languages (verified empirically, see DESIGN.md).
BRACE_NESTING_LANGUAGES = frozenset(
    {
        "cpp", "java", "csharp", "javascript", "typescript", "tsx", "objectivec", "swift", "scala",
        "go", "rust", "kotlin", "php", "dart", "solidity", "zig", "perl", "r", "ttcn", "vue",
    }
)


@dataclass(frozen=True)
class LizardFunction:
    name: str  # lizard's short name, e.g. "A::f" or "outer.inner"
    qualified_name: str  # "." separated
    start_line: int
    end_line: int
    cyclomatic_complexity: int
    nloc: int
    parameters: tuple[str, ...]
    parameter_count: int
    max_nesting_depth: int
    cognitive_complexity: int

    @property
    def unqualified_name(self) -> str:
        return self.qualified_name.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class LizardFile:
    language: str
    nloc: int
    functions: tuple[LizardFunction, ...]


def version() -> str:
    return str(_lizard_version)


@cache
def extension_map() -> dict[str, tuple[str, str]]:
    """Map a lower-case file suffix to (language name, suffix lizard recognises)."""
    mapping: dict[str, tuple[str, str]] = {}
    for reader in _lizard_readers():
        language = reader.language_names[0].lower()
        for ext in reader.ext:
            mapping.setdefault(f".{ext.lower()}", (language, f".{ext}"))
    return mapping


def language_for(path: str | Path) -> str | None:
    found = extension_map().get(Path(path).suffix.lower())
    return found[0] if found else None


def _lizard_filename(path: str | Path, language: str) -> str:
    """A file name lizard maps to the reader for ``language`` (e.g. ``.pyi`` -> ``.py``)."""
    found = extension_map().get(Path(path).suffix.lower())
    if found:  # lizard knows this suffix: let it pick its reader (e.g. .jsx -> TSX reader)
        return f"source{found[1]}"
    for lang, ext in extension_map().values():
        if lang == language:
            return f"source{ext}"
    raise ValueError(f"lizard does not support language: {language}")


def _qualified(name: str, long_name: str) -> str:
    """lizard's scoped name from the signature head (``A::f(int)`` -> ``A.f``) when it is a plain path."""
    head = long_name.split("(", 1)[0].strip()
    short = name.split("::")[-1].split(".")[-1]
    chosen = head if _is_plain_path(head, short) else name
    return chosen.replace("::", ".")


def _is_plain_path(head: str, short: str) -> bool:
    return bool(head) and " " not in head and head.endswith(short)


def extensions_used(with_nesting: bool) -> tuple[str, ...]:
    """The lizard extensions a run uses; ``nd`` only when lizard supplies nesting depth."""
    return tuple(e for e in EXTENSIONS_USED if with_nesting or e != "nd")


@cache
def _analyzer_extensions(with_nesting: bool) -> tuple:
    return tuple(get_extensions(list(extensions_used(with_nesting))))


def analyze(source: str, path: str | Path, language: str, *, with_nesting: bool = True) -> LizardFile:
    """lizard metrics; ``with_nesting=False`` skips the ``nd`` pass when tree-sitter supplies nesting."""
    analyzer = FileAnalyzer(list(_analyzer_extensions(with_nesting)))
    info = analyzer.analyze_source_code(_lizard_filename(path, language), source)
    functions = tuple(
        LizardFunction(
            name=f.name,
            qualified_name=_qualified(f.name, f.long_name),
            start_line=f.start_line,
            end_line=f.end_line,
            cyclomatic_complexity=f.cyclomatic_complexity,
            nloc=f.nloc,
            parameters=tuple(f.parameters),
            parameter_count=f.parameter_count,
            max_nesting_depth=getattr(f, "max_nesting_depth", 0),
            cognitive_complexity=getattr(f, "cognitive_complexity", 0),
        )
        for f in info.function_list
    )
    return LizardFile(language=language, nloc=info.nloc, functions=functions)


def nesting_is_reliable(language: str) -> bool:
    return language in BRACE_NESTING_LANGUAGES
