"""Command line: ``codehealth score|review|delta|serve|install-pmd``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path

from . import __version__
from .analysis import FileReview, review_files
from .lang import is_supported

SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "fixtures"})


def iter_sources(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_dir():
            yield from _walk_dir(path)
        else:
            yield path


def _walk_dir(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if _is_reviewable(root, path):
            yield path


def _is_reviewable(root: Path, path: Path) -> bool:
    """A supported source file outside skipped directories (.git, .venv, fixtures, ...)."""
    skipped = bool(SKIP_DIRS & set(path.relative_to(root).parts[:-1]))
    return path.is_file() and is_supported(path) and not skipped


def _print_review(review: FileReview, with_findings: bool) -> None:
    print(f"{review.path}: {review.score:.2f} ({review.category})")
    if not with_findings:
        return
    for f in review.findings:
        where = f" {f.function}" if f.function else ""
        lines = f" [lines {f.start_line}-{f.end_line}]" if f.start_line is not None else ""
        print(f"  - {f.smell}{where}{lines} {f.message}")


def cmd_score_or_review(args: argparse.Namespace, with_findings: bool) -> int:
    reviews = review_files(list(iter_sources(args.paths)))
    if args.json:
        print(json.dumps([r.to_dict(include_findings=with_findings) for r in reviews], indent=2))
    else:
        for review in reviews:
            _print_review(review, with_findings)
    return 0


def cmd_delta(args: argparse.Namespace) -> int:
    from . import delta

    if args.files:
        repo = delta.repo_root(Path(args.files[0]).resolve())
        files = [Path(f).resolve().relative_to(repo).as_posix() for f in args.files]
        result = delta.summarize([delta.file_delta_against_ref(repo, f, args.ref) for f in files])
    elif args.base:
        result = delta.analyze_change_set(delta.repo_root(Path.cwd()), args.base)
    else:
        result = delta.pre_commit_safeguard(delta.repo_root(Path.cwd()))
    print(json.dumps(result, indent=2))
    return 0 if result["quality_gate"] == "passed" else 1


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import main as serve

    serve([])
    return 0


def cmd_install_pmd(args: argparse.Namespace) -> int:
    from . import pmd_install

    install_dir = Path(args.dir) if args.dir else pmd_install.default_install_dir()
    print(f"Installing PMD {pmd_install.PMD_VERSION} into {install_dir} (SHA-256 {pmd_install.PMD_SHA256})")
    home = pmd_install.install(install_dir)
    print(f"PMD {pmd_install.PMD_VERSION} is at {home}")
    if args.dir:
        print(f"Set CODEHEALTH_PMD_HOME={home} so codehealth finds it.")
    print("PMD needs a Java runtime (8+) on PATH or in JAVA_HOME.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codehealth", description="Code Health analysis")
    parser.add_argument("--version", action="version", version=f"codehealth {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("score", "review"):
        p = sub.add_parser(name, help=f"{name} files or directories")
        p.add_argument("paths", nargs="*", default=["."])
        p.add_argument("--json", action="store_true")
    d = sub.add_parser("delta", help="compare files with a git ref (default: uncommitted vs HEAD)")
    d.add_argument("files", nargs="*")
    d.add_argument("--ref", default="HEAD", help="ref for explicit files")
    d.add_argument("--base", help="compare HEAD with merge-base of this ref")
    sub.add_parser("serve", help="run the MCP server on stdio (same as codehealth-mcp)")
    i = sub.add_parser("install-pmd", help="download the pinned PMD release (optional; needs Java to run)")
    i.add_argument("--dir", help="install directory (default: $CODEHEALTH_PMD_HOME or the user data directory)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            return cmd_serve(args)
        if args.command == "delta":
            return cmd_delta(args)
        if args.command == "install-pmd":
            return cmd_install_pmd(args)
        return cmd_score_or_review(args, with_findings=args.command == "review")
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"codehealth: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
