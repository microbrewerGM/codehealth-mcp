"""MCP stdio server exposing the Code Health tools (official MCP Python SDK)."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import config, delta, explain, smells
from . import thresholds as th
from .analysis import review_file
from .lang import EXTENSIONS, is_supported

server = MCPServer(
    name="codehealth",
    instructions=(
        "Maintainability analysis for the ~30 languages lizard reads (Python, JavaScript, TypeScript/TSX, "
        "Java, Go, C/C++, C#, Ruby, Kotlin, Swift, Rust, PHP and more). "
        "Scores files 1-10 (Healthy >= 9, Warning >= 4, Alert < 4) and lists code smells. "
        "All paths must be absolute."
    ),
)


Result = dict[str, Any]


def _json(data: dict) -> Result:
    """A JSON-safe copy of ``data`` (paths and other objects become strings).

    Tools return dicts so the SDK sends them as structured content (an object
    clients can read directly) plus the same JSON as text for older clients.
    """
    return json.loads(json.dumps(data, default=str))


def _tool_errors(fn: Callable[..., Result]) -> Callable[..., Result]:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> Result:
        try:
            return fn(*args, **kwargs)
        except (ValueError, OSError, delta.GitError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def _source_file(file_path: str) -> Path:
    path = Path(file_path)
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {file_path}")
    if not path.is_file():
        raise ValueError(f"file not found: {file_path}")
    if not is_supported(path):
        raise ValueError(f"unsupported file type '{path.suffix}'; supported: {', '.join(sorted(EXTENSIONS))}")
    return path


def _repo(repository_path: str) -> Path:
    path = Path(repository_path)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"repository path must be an existing absolute directory: {repository_path}")
    return delta.repo_root(path)


@server.tool()
@_tool_errors
def code_health_score(file_path: str) -> Result:
    """Score one source file for maintainability.

    When to use: a quick health check of a file before or after editing it.
    Limitations: one file at a time; some smells need a tree-sitter adapter
    (Python, JS, TS/TSX, Java, Go) or PMD, see the analyzers field.
    Returns: {path, language, score 1-10, category, optimal, analyzers}.
    """
    return _json(review_file(_source_file(file_path)).to_dict(include_findings=False))


@server.tool()
@_tool_errors
def code_health_review(file_path: str) -> Result:
    """Review one source file and list its code smells.

    When to use: to decide what to refactor, or to check that an edit did not
    add smells. Fix the findings with the highest severity first.
    Limitations: static analysis of a single file; duplication within the
    file only (needs PMD). analyzers lists which analyzers ran and which
    smells were unavailable for this language.
    Returns: {score, category, findings:[{smell, level, function,
    start_line, end_line (null for whole-file findings), value, threshold,
    severity, message, hint, details}],
    pmd_violations?, analyzers:{lizard, tree_sitter, pmd, unavailable_smells}}.
    """
    return _json(review_file(_source_file(file_path)).to_dict())


@server.tool()
@_tool_errors
def pre_commit_code_health_safeguard(repository_path: str) -> Result:
    """Check staged and modified files against HEAD before committing.

    When to use: before every commit made by an agent.
    Limitations: tracked files only (untracked files are skipped); compares
    the working tree with HEAD using HEAD's root rules file for both sides.
    Returns: {quality_gate: passed|failed, counts, rules_changed?,
    files:[{path, verdict (improved|degraded|stable|removed|unknown),
    old_score, new_score, new_findings, worsened, improved, fixed}],
    cross_file_duplication?: CPD copies and renamed clones between changed files (informational),
    analyzers?}.
    """
    return _json(delta.pre_commit_safeguard(_repo(repository_path)))


@server.tool()
@_tool_errors
def analyze_change_set(repository_path: str, base_ref: str = "main") -> Result:
    """Compare every changed file on the current branch with its merge base.

    When to use: before opening or merging a pull request.
    Limitations: compares committed HEAD content only; uncommitted edits are
    ignored. The merge base's root rules file is used for both sides.
    Returns: {quality_gate, merge_base, counts, rules_changed?, files:[{path, verdict, ...}],
    cross_file_duplication?, analyzers?}.
    """
    return _json(delta.analyze_change_set(_repo(repository_path), base_ref))


@server.tool()
@_tool_errors
def rules_config_validate(repository_path: str) -> Result:
    """Validate the repository's code health rules file.

    When to use: after editing .codehealth/rules.json.
    Limitations: checks structure, rule names and threshold names only.
    Returns: {rules_file, valid, errors}.
    """
    repo = _repo(repository_path)
    path = config.config_file_for_repo(repo)
    if not path.is_file() and not path.is_symlink():
        return _json({"rules_file": None, "valid": True, "errors": [], "note": "no rules file; defaults apply"})
    path = config.safe_config_target(repo, path)  # refuses symlinked or out-of-repo paths
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Report position only; never echo file content.
        return _json({"rules_file": str(path), "valid": False, "errors": [f"invalid JSON: {exc.msg} at line {exc.lineno}"]})
    errors = config.validate_config(data)
    return _json({"rules_file": str(path), "valid": not errors, "errors": errors})


@server.tool()
@_tool_errors
def rules_config_list_thresholds(language: str = "") -> Result:
    """List every threshold with its default value and source.

    When to use: before overriding a threshold, to see names and defaults.
    Limitations: shows defaults, not a repository's overrides.
    Languages without their own template fall back to the baseline values
    (template: false).
    Returns: {language, template, thresholds:[{name, value, operator, published, description}], rules:[names]}.
    """
    language = language.strip().lower()
    values = th.defaults_for(language) if language else dict(th.DEFAULTS)
    rows = [
        {
            "name": name,
            "value": value,
            "operator": th.OPERATORS.get(name, th.GE),
            "published": th.PUBLISHED.get(name, True),
            "description": th.DESCRIPTIONS.get(name, ""),
        }
        for name, value in sorted(values.items())
    ]
    return _json(
        {
            "language": language or "default",
            "template": th.has_template(language) if language else True,
            "thresholds": rows,
            "rules": sorted(smells.KNOWN_RULES),
        }
    )


@server.tool()
@_tool_errors
def rules_config_set_rule(repository_path: str, rule_name: str, weight: float, matching_content_path: str = "**/*") -> Result:
    """Set a rule's weight in the repository rules file (0 disables the rule).

    When to use: to silence or soften a smell for part of a repository.
    Limitations: writes the rules file in the repository root; the first
    matching rule set wins, so a new specific glob is placed first.
    Returns: {rules_file, rule, weight, matching_content_path}.
    """
    path = config.set_rule(_repo(repository_path), rule_name, weight, matching_content_path)
    return _json({"rules_file": str(path), "rule": rule_name, "weight": weight, "matching_content_path": matching_content_path})


@server.tool()
@_tool_errors
def rules_config_set_threshold(
    repository_path: str, threshold_name: str, value: float, matching_content_path: str = "**/*"
) -> Result:
    """Override a threshold in the repository rules file.

    When to use: when a team agrees on a different limit, e.g. longer functions in tests.
    Limitations: names must come from rules_config_list_thresholds.
    Returns: {rules_file, threshold, value, matching_content_path}.
    """
    path = config.set_threshold(_repo(repository_path), threshold_name, value, matching_content_path)
    return _json(
        {"rules_file": str(path), "threshold": threshold_name, "value": value, "matching_content_path": matching_content_path}
    )


@server.tool()
@_tool_errors
def explain_code_health(topic: str = "") -> Result:
    """Explain the Code Health model, a smell, or the score bands.

    When to use: to understand a finding or how the score is computed.
    Limitations: static documentation; pass a smell name or 'score' as topic.
    Returns: {topic, text}.
    """
    return _json(explain.explain(topic))


def main(argv: list[str] | None = None) -> None:
    """Entry point of ``codehealth-mcp``: run the MCP server on stdio."""
    import argparse

    from . import __version__

    parser = argparse.ArgumentParser(
        prog="codehealth-mcp",
        description="Run the Code Health MCP server on stdio (for MCP clients such as Claude Code, Codex, Cursor).",
    )
    parser.add_argument("--version", action="version", version=f"codehealth-mcp {__version__}")
    parser.parse_args(argv)
    server.run("stdio")
