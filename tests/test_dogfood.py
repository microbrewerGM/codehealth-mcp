"""scripts/dogfood.py: our own MCP server over stdio, and the src/ gate."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

from .conftest import FIXTURES

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dogfood.py"


def _load():
    spec = importlib.util.spec_from_file_location("dogfood", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dogfood"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def test_reviews_through_the_mcp_server(monkeypatch):
    monkeypatch.setenv("CODEHEALTH_NO_PMD", "1")
    dogfood = _load()
    [result] = asyncio.run(dogfood.review_all([FIXTURES / "python" / "smelly.py"]))
    assert result.score < 9.0
    assert "Complex Method" in {f["smell"] for f in result.findings}


def test_gate_applies_to_src_only():
    dogfood = _load()
    src = dogfood.Result(dogfood.ROOT / "src" / "x.py", 8.5, [])
    bench = dogfood.Result(dogfood.ROOT / "bench" / "y.py", 7.0, [])
    good = dogfood.Result(dogfood.ROOT / "src" / "z.py", 10.0, [])
    assert src.gated and not bench.gated and not good.gated
    lines = dogfood.report([good, src, bench], show_all=False)
    assert lines[0].startswith(" 7.00  bench/y.py") and "src/x.py  FAIL" in lines[1]
    assert lines[-1] == "3 files reviewed, 1 at 10.0, 1 src/ file(s) below 9.0."
