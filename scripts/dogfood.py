"""Dogfood: review this project's own code through its MCP server.

Starts ``codehealth serve`` over stdio with the official MCP client SDK, calls
``code_health_review`` for every Python file under ``src/`` and ``bench/``,
and prints a report sorted by score (worst first). Exits 1 when any file
under ``src/`` scores below 9.0 (Healthy).

Usage: uv run python scripts/dogfood.py [--all]   (--all also lists 10.0 files)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("src", "bench")
HEALTHY = 9.0
# Settings the server needs from our environment (PMD location, Java, cache).
PASSED_ENV = ("CODEHEALTH_PMD_HOME", "CODEHEALTH_NO_PMD", "CODEHEALTH_PMD_TIMEOUT", "CODEHEALTH_CACHE_DIR",
              "JAVA_HOME", "XDG_CACHE_HOME")


@dataclass(frozen=True)
class Result:
    path: Path
    score: float
    findings: list[dict]

    @property
    def relpath(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def gated(self) -> bool:
        """Files under src/ must be Healthy."""
        return self.relpath.startswith("src/") and self.score < HEALTHY


def source_files() -> list[Path]:
    return sorted(p for scope in SCOPES for p in (ROOT / scope).rglob("*.py") if "__pycache__" not in p.parts)


def server_parameters() -> StdioServerParameters:
    env = get_default_environment() | {k: os.environ[k] for k in PASSED_ENV if k in os.environ}
    exe = shutil.which("codehealth")
    if exe is not None:
        return StdioServerParameters(command=exe, args=["serve"], env=env, cwd=ROOT)
    return StdioServerParameters(command=sys.executable, args=["-m", "codehealth.cli", "serve"], env=env, cwd=ROOT)


async def review(session: ClientSession, path: Path) -> Result:
    reply = await session.call_tool("code_health_review", {"file_path": str(path)})
    if getattr(reply, "is_error", False):
        text = "".join(getattr(block, "text", "") for block in reply.content)
        raise RuntimeError(f"{path}: {text}")
    data = reply.structured_content
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: expected structured content, got {type(data).__name__}")
    return Result(path, data["score"], data.get("findings", []))


async def review_all(paths: list[Path]) -> list[Result]:
    async with stdio_client(server_parameters()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return [await review(session, p) for p in paths]


def describe(finding: dict) -> str:
    where = f" {finding['function']}" if finding.get("function") else ""
    return f"    - {finding['smell']}{where}: {finding['message']}"


def describe_file(r: Result) -> list[str]:
    mark = "  FAIL" if r.gated else ""
    return [f"{r.score:5.2f}  {r.relpath}{mark}"] + [describe(f) for f in r.findings]


def visible(results: list[Result], show_all: bool) -> list[Result]:
    """Worst first; 10.0 files only with --all."""
    ordered = sorted(results, key=lambda r: (r.score, r.relpath))
    return ordered if show_all else [r for r in ordered if r.score < 10.0]


def report(results: list[Result], show_all: bool) -> list[str]:
    lines = [line for r in visible(results, show_all) for line in describe_file(r)]
    perfect = sum(r.score >= 10.0 for r in results)
    failing = sum(r.gated for r in results)
    return lines + [f"{len(results)} files reviewed, {perfect} at 10.0, {failing} src/ file(s) below {HEALTHY}."]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="also list files that score 10.0")
    args = ap.parse_args(argv)
    results = asyncio.run(review_all(source_files()))
    print("\n".join(report(results, args.all)))
    return 1 if any(r.gated for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
