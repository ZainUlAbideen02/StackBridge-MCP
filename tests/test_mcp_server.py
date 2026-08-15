"""Tests for MCP server tools, ContextFormatter token savings, and CLI entry points."""

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from stackbridge.main import run_index, run_trace
from stackbridge.mcp_server.formatter import ContextFormatter
from stackbridge.mcp_server.server import get_route_contract, trace_fullstack_path


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"


def test_mcp_tool_trace_fullstack_path():
    result = trace_fullstack_path(
        repo_path=str(FIXTURES_DIR),
        target="backend/models.py::BillingAccount",
    )

    assert result["found"] is True
    assert result["target"] == "backend/models.py::BillingAccount"
    assert len(result["chains"]) >= 1

    # Verify full chain: UserProfile.tsx -> /api/v1/users/{user_id}/billing -> BillingAccount
    full_chain = result["full_chain"]
    assert len(full_chain) == 3
    assert "UserProfile.tsx" in full_chain[0]
    assert "/api/v1/users/{user_id}/billing" in full_chain[1] or "get_user_billing" in full_chain[1]
    assert "BillingAccount" in full_chain[2]

    # Verify impacted files
    impacted = result["impacted_files"]
    assert "frontend/UserProfile.tsx" in impacted
    assert "backend/routes.py" in impacted
    assert "backend/models.py" in impacted


def test_mcp_tool_get_route_contract():
    result = get_route_contract(
        repo_path=str(FIXTURES_DIR),
        route_path="/api/v1/users/{user_id}/billing",
    )

    assert result["found"] is True
    assert result["route_path"] == "/api/v1/users/{user_id}/billing"
    assert result["http_method"] == "GET"
    assert result["handler_name"] == "get_user_billing"
    assert result["response_model"] == "BillingAccountOut"
    assert 200 in result["status_codes"]
    assert 404 in result["status_codes"]
    assert "user_id" in result["path_params"]
    assert "BillingAccount" in result["models_accessed"]

    # Verify linked fetch calls and confidence
    linked = result["linked_callers"]
    assert len(linked) == 1
    caller = linked[0]
    assert "UserProfile.tsx" in caller["file_path"]
    assert caller["confidence"] == 0.88
    assert caller["is_exact"] is False
    assert caller["param_mappings"] == {"userId": "user_id"}


def test_mcp_tool_get_route_contract_static_route():
    result = get_route_contract(
        repo_path=str(FIXTURES_DIR),
        route_path="/api/v1/teams",
    )

    assert result["found"] is True
    assert result["handler_name"] == "get_teams"
    assert result["response_model"] == "List[TeamOut]"
    assert len(result["linked_callers"]) == 1
    assert result["linked_callers"][0]["confidence"] == 1.0


def test_context_formatter_token_savings():
    # Read raw source files from fixtures
    frontend_code = (FIXTURES_DIR / "frontend" / "UserProfile.tsx").read_text(encoding="utf-8")
    backend_routes = (FIXTURES_DIR / "backend" / "routes.py").read_text(encoding="utf-8")
    backend_models = (FIXTURES_DIR / "backend" / "models.py").read_text(encoding="utf-8")

    raw_files = {
        "UserProfile.tsx": frontend_code,
        "routes.py": backend_routes,
        "models.py": backend_models,
    }

    # Extract target route contract compact slice
    contract = get_route_contract(str(FIXTURES_DIR), "/api/v1/users/{user_id}/billing")
    formatted_slice = ContextFormatter.format_route_contract(contract)

    savings = ContextFormatter.calculate_token_savings(raw_files, formatted_slice)

    assert savings["raw_tokens"] > 0
    assert savings["slice_tokens"] > 0
    assert savings["tokens_saved"] > 0
    assert savings["percentage_saved"] > 50.0  # Significant token savings (>50%)


def test_cli_index_and_trace(tmp_path, capsys):
    # 1. Test run_index function
    custom_output = tmp_path / "custom_graph.json"
    index_ret = run_index(repo_path=str(FIXTURES_DIR), output=str(custom_output))
    assert index_ret == 0
    assert custom_output.exists()
    
    with open(custom_output, "r", encoding="utf-8") as f:
        graph_data = json.load(f)
    assert graph_data["node_count"] >= 6
    assert graph_data["edge_count"] >= 5

    # 2. Test run_trace function
    trace_ret = run_trace(repo_path=str(FIXTURES_DIR), target="BillingAccount")
    assert trace_ret == 0
    captured = capsys.readouterr()
    assert "UserProfile.tsx -> /api/v1/users/{user_id}/billing -> BillingAccount" in captured.out


def test_cli_subprocess_execution():
    # Test executing CLI via python -m stackbridge.main
    res_index = subprocess.run(
        [sys.executable, "-m", "stackbridge.main", "index", "--repo-path", str(FIXTURES_DIR)],
        capture_output=True,
        text=True,
    )
    assert res_index.returncode == 0
    assert "Indexed" in res_index.stdout

    res_trace = subprocess.run(
        [sys.executable, "-m", "stackbridge.main", "trace", "--repo-path", str(FIXTURES_DIR), "--target", "BillingAccount"],
        capture_output=True,
        text=True,
    )
    assert res_trace.returncode == 0
    assert "Full-Stack Dependency Trace" in res_trace.stdout
    assert "UserProfile.tsx" in res_trace.stdout
