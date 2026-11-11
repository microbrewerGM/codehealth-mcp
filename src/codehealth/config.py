"""Rules configuration and comment directives.

Reads ``.codehealth/rules.json``:
``{"rule_sets": [{"matching_content_path": glob, "rules": [{name, weight}],
"thresholds": [{name, value}]}]}``. Only the first rule set whose glob
matches the file applies; rule sets do not merge.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import globmatch
from . import thresholds as th
from .lang.base import ParsedFile
from .smells import FILE_LEVEL_SMELLS, KNOWN_RULES

CONFIG_PATHS = (Path(".codehealth/rules.json"),)
DEFAULT_PATTERN = "**/*"
DISABLE_ALL = "*"

_DIRECTIVE = re.compile(r"@codehealth\(([^)\n]{0,200})\)")  # bounded: comments come from untrusted repos
_DISABLE = re.compile(r"disable\s*:\s*\"([^\"]+)\"")


class ConfigError(ValueError):
    pass


@dataclass
class Rules:
    thresholds: dict[str, float]
    weights: dict[str, float] = field(default_factory=dict)
    config_path: str | None = None
    matched_pattern: str | None = None

    def weight(self, smell: str) -> float:
        return self.weights.get(smell, 1.0)


# ----- locating files --------------------------------------------------------
def find_repo_root(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def find_config(path: Path) -> Path | None:
    """Return the nearest rules file at or above ``path``, never above the repo root.

    Outside a git repository only the file's own directory is searched.
    """
    start = path if path.is_dir() else path.parent
    root = find_repo_root(path)
    candidates = [start] if root is None else [start, *start.parents]
    for candidate in candidates:
        found = next((candidate / p for p in CONFIG_PATHS if (candidate / p).is_file()), None)
        if found is not None or candidate == root:
            return found
    return None


def config_base(config_path: Path) -> Path:
    """Globs are relative to the directory that holds the config directory."""
    return config_path.parent.parent


# ----- glob matching ---------------------------------------------------------
def glob_match(pattern: str, relpath: str) -> bool:
    """Match a repo-relative path; see :mod:`codehealth.globmatch` for the limits."""
    return globmatch.glob_match(pattern, relpath)


# ----- loading -----------------------------------------------------------------
def load_config(config_path: Path) -> dict:
    """Read and validate a rules file, refusing paths reached through symlinks."""
    root = find_repo_root(config_path) or config_base(config_path)
    safe_config_target(root, config_path)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {config_path}: {exc.strerror}") from exc
    return parse_config(text, str(config_path))


def parse_config(text: str, source: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {source}: {exc.msg} at line {exc.lineno}") from exc
    errors = validate_config(data)
    if errors:
        raise ConfigError(f"invalid {source}: " + "; ".join(errors))
    return data


MAX_NAME_IN_MESSAGE = 80


def quote_name(name: str) -> str:
    """Quote an untrusted name for an error message, truncated to a fixed length."""
    clipped = name[:MAX_NAME_IN_MESSAGE] + ("..." if len(name) > MAX_NAME_IN_MESSAGE else "")
    return json.dumps(clipped)


def validate_config(data: object) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("rule_sets"), list):
        return ["top level must be an object with a 'rule_sets' list"]
    errors: list[str] = []
    for index, rule_set in enumerate(data["rule_sets"]):
        errors.extend(f"rule_sets[{index}]: {e}" for e in _validate_rule_set(rule_set))
    return errors


def _validate_rule_set(rule_set: object) -> list[str]:
    if not isinstance(rule_set, dict):
        return ["must be an object"]
    errors = []
    pattern = rule_set.get("matching_content_path", DEFAULT_PATTERN)
    if not isinstance(pattern, str):
        errors.append("matching_content_path must be a string")
    elif (glob_error := globmatch.validate(pattern)) is not None:
        errors.append(f"matching_content_path: {glob_error}")
    errors += _validate_entries(rule_set.get("rules", []), "weight", _rule_name_ok, "rule")
    errors += _validate_entries(rule_set.get("thresholds", []), "value", th.is_known, "threshold")
    return errors


def _rule_name_ok(name: str) -> bool:
    return name in KNOWN_RULES


def _validate_entries(entries: object, value_key: str, name_ok, kind: str) -> list[str]:
    if not isinstance(entries, list):
        return [f"{kind}s must be a list"]
    errors = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            errors.append(f"each {kind} needs a string 'name'")
        elif not name_ok(entry["name"]):
            errors.append(f"unknown {kind} {quote_name(entry['name'])}")
        elif not _is_non_negative(entry.get(value_key)):
            errors.append(f"{kind} {quote_name(entry['name'])} needs a non-negative number '{value_key}'")
    return errors


def _is_non_negative(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def rules_for(file_path: Path, language: str) -> Rules:
    """Defaults for ``language`` plus the first matching rule set, if any."""
    config_path = find_config(file_path)
    if config_path is None:
        return Rules(thresholds=th.defaults_for(language))
    relpath = _relative(file_path, config_base(config_path))
    return rules_from_data(load_config(config_path), relpath, language, str(config_path))


def rules_from_data(data: dict | None, relpath: str, language: str, source: str | None = None) -> Rules:
    """Apply the first rule set of an already validated config that matches ``relpath``."""
    rules = Rules(thresholds=th.defaults_for(language), config_path=source)
    for rule_set in (data or {}).get("rule_sets", []):
        pattern = rule_set.get("matching_content_path", DEFAULT_PATTERN)
        if glob_match(pattern, relpath):
            _apply_rule_set(rules, rule_set, pattern)
            break
    return rules


def _relative(file_path: Path, base: Path) -> str:
    try:
        return file_path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return file_path.name


def _apply_rule_set(rules: Rules, rule_set: dict, pattern: str) -> None:
    rules.matched_pattern = pattern
    rules.weights.update({r["name"]: float(r["weight"]) for r in rule_set.get("rules", [])})
    rules.thresholds.update({t["name"]: float(t["value"]) for t in rule_set.get("thresholds", [])})


# ----- directives ----------------------------------------------------------------
def disabled_smells(parsed: ParsedFile) -> dict[str, set[str]]:
    """Map function qualified name to the smells its directive disables.

    A directive applies to the next function that starts on or after the
    comment. ``DISABLE_ALL`` in the set means every function-level smell.
    """
    result: dict[str, set[str]] = {}
    for comment in parsed.comments:
        smells = _directive_smells(comment.text)
        target = _next_function(parsed, comment.start_line) if smells else None
        if target is not None:
            result.setdefault(target, set()).update(smells)
    return result


def _directive_smells(text: str) -> set[str]:
    smells: set[str] = set()
    for body in _DIRECTIVE.findall(text):
        if "disable-all" in body:
            smells.add(DISABLE_ALL)
        smells.update(s for s in _DISABLE.findall(body) if s not in FILE_LEVEL_SMELLS)
    return smells


def _next_function(parsed: ParsedFile, line: int) -> str | None:
    # parsed.functions is sorted by start line.
    index = bisect.bisect_left([f.start_line for f in parsed.functions], line)
    return parsed.functions[index].qualified_name if index < len(parsed.functions) else None


# ----- editing ---------------------------------------------------------------------
def config_file_for_repo(repo_root: Path) -> Path:
    existing = next((repo_root / p for p in CONFIG_PATHS if (repo_root / p).is_file()), None)
    return existing or repo_root / CONFIG_PATHS[0]


def set_rule(repo_root: Path, name: str, weight: float, pattern: str = DEFAULT_PATTERN) -> Path:
    """Set a rule weight in the repository rules file (0 disables the rule)."""
    return set_entry(repo_root, "rules", (name, weight), pattern)


def set_threshold(repo_root: Path, name: str, value: float, pattern: str = DEFAULT_PATTERN) -> Path:
    """Override a threshold in the repository rules file."""
    return set_entry(repo_root, "thresholds", (name, value), pattern)


def set_entry(repo_root: Path, kind: str, entry: tuple[str, float], pattern: str = DEFAULT_PATTERN) -> Path:
    """Set a rule weight (kind='rules') or threshold (kind='thresholds') and save."""
    name, value = entry
    config_path = safe_config_target(repo_root, config_file_for_repo(repo_root))
    data = load_config(config_path) if config_path.is_file() else {"rule_sets": []}
    rule_set = _rule_set_for(data, pattern)
    value_key = "weight" if kind == "rules" else "value"
    entries = [e for e in rule_set.setdefault(kind, []) if e.get("name") != name]
    rule_set[kind] = entries + [{"name": name, value_key: value}]
    errors = validate_config(data)
    if errors:
        raise ConfigError("; ".join(errors))
    _atomic_write(repo_root, config_path, json.dumps(data, indent=2) + "\n")
    return config_path


def safe_config_target(repo_root: Path, config_path: Path) -> Path:
    """Refuse targets outside the repo, non-JSON targets and symlinked components.

    Rules files live in repositories we do not trust; a symlinked
    ``.codehealth`` directory or rules file must not redirect our write.
    """
    root = repo_root.resolve(strict=True)
    try:
        target = root / config_path.relative_to(repo_root)
    except ValueError:
        target = Path(config_path)
    if target.suffix != ".json" or not target.is_relative_to(root):
        raise ConfigError(f"refusing to write rules file outside the repository: {config_path}")
    _refuse_symlinks(root, target)
    if not target.resolve().is_relative_to(root):
        raise ConfigError(f"refusing to write rules file outside the repository: {config_path}")
    return target


def _refuse_symlinks(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise ConfigError(f"refusing to write through symlink: {current}")


def _atomic_write(repo_root: Path, target: Path, text: str) -> None:
    """Write via a temp file in the target directory, then rename over the target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    _refuse_symlinks(repo_root.resolve(), target)  # re-check after creating directories
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".rules-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _rule_set_for(data: dict, pattern: str) -> dict:
    for rule_set in data["rule_sets"]:
        if rule_set.get("matching_content_path", DEFAULT_PATTERN) == pattern:
            return rule_set
    rule_set = {"matching_content_path": pattern, "rules": [], "thresholds": []}
    # First match wins, so the catch-all goes last and specific globs go first.
    position = len(data["rule_sets"]) if pattern == DEFAULT_PATTERN else 0
    data["rule_sets"].insert(position, rule_set)
    return rule_set
