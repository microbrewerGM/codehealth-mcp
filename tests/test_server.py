"""MCP smoke tests: the server runs in-process through the SDK client."""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from codehealth.server import server

from .conftest import FIXTURES

TOOLS = {
    "code_health_score",
    "code_health_review",
    "pre_commit_code_health_safeguard",
    "analyze_change_set",
    "rules_config_validate",
    "rules_config_list_thresholds",
    "rules_config_set_rule",
    "rules_config_set_threshold",
    "explain_code_health",
}


async def _call(name: str, args: dict):
    async with Client(server) as client:
        return await client.call_tool(name, args)


def call(name: str, args: dict):
    return asyncio.run(_call(name, args))


async def _list():
    async with Client(server) as client:
        return await client.list_tools()


def test_lists_all_tools_with_descriptions():
    tools = asyncio.run(_list()).tools
    assert {t.name for t in tools} == TOOLS
    for tool in tools:
        assert "When to use" in tool.description and "Returns" in tool.description


def test_code_health_review_over_mcp():
    result = call("code_health_review", {"file_path": str(FIXTURES / "python" / "smelly.py")})
    assert not result.is_error
    data = result.structured_content
    assert data["category"] == "Warning"
    assert {"smell": "Bumpy Road Ahead", "function": "bumpy"}.items() <= {
        k: v for k, v in next(f for f in data["findings"] if f["smell"] == "Bumpy Road Ahead").items()
    }.items()


def test_tools_return_structured_objects():
    """Results arrive as a structured object (not a JSON string wrapped in {"result": ...})."""
    result = call("code_health_score", {"file_path": str(FIXTURES / "python" / "clean.py")})
    assert not result.is_error
    data = result.structured_content
    assert isinstance(data, dict) and "result" not in data
    assert isinstance(data["score"], float) and data["category"] == "Healthy"
    assert isinstance(data["analyzers"], dict)
    assert json.loads(result.content[0].text) == data  # text mirror for clients without structured content


def test_tools_publish_object_output_schemas():
    for tool in asyncio.run(_list()).tools:
        assert tool.output_schema is not None and tool.output_schema["type"] == "object", tool.name


def test_rejects_relative_missing_and_unsupported_paths(tmp_path):
    (tmp_path / "x.txt").write_text("hi")
    for path in ("relative.py", str(tmp_path / "missing.py"), str(tmp_path / "x.txt")):
        result = call("code_health_score", {"file_path": path})
        assert result.is_error
    assert "absolute" in call("code_health_score", {"file_path": "relative.py"}).content[0].text


def test_rules_tools_round_trip(repo):
    call("rules_config_set_rule", {"repository_path": str(repo), "rule_name": "Large Method", "weight": 0})
    data = call("rules_config_validate", {"repository_path": str(repo)}).structured_content
    assert data["valid"] is True
    bad = call("rules_config_set_threshold", {"repository_path": str(repo), "threshold_name": "nope", "value": 1})
    assert bad.is_error
    listing = call("rules_config_list_thresholds", {"language": "python"}).structured_content
    by_name = {t["name"]: t for t in listing["thresholds"]}
    assert by_name["file_lines_of_code_for_warning"]["value"] == 600
    assert by_name["function_max_arguments"]["operator"] == ">"


def test_explain():
    text = call("explain_code_health", {"topic": "score"}).structured_content["text"]
    assert "exp(" in text


def test_thresholds_fall_back_to_baseline_without_template():
    listing = call("rules_config_list_thresholds", {"language": "csharp"}).structured_content
    assert listing["template"] is False
    by_name = {t["name"]: t["value"] for t in listing["thresholds"]}
    assert by_name["file_lines_of_code_for_warning"] == 1000  # baseline value
    ruby = call("rules_config_list_thresholds", {"language": "Ruby"}).structured_content
    assert ruby["template"] is True
    assert {t["name"]: t["value"] for t in ruby["thresholds"]}["file_lines_of_code_for_warning"] == 600


def test_review_reports_analyzers_over_mcp():
    data = call("code_health_score", {"file_path": str(FIXTURES / "ruby" / "smelly.rb")}).structured_content
    assert data["language"] == "ruby"
    assert data["analyzers"]["lizard"]["ran"] is True
    assert "Bumpy Road Ahead" in data["analyzers"]["unavailable_smells"]
