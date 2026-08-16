"""End-to-end tests for StackBridge MCP Server using the Mock MCP Client."""

import asyncio
import subprocess
import sys
from pathlib import Path
import pytest

from scripts.test_mcp_client import run_mcp_client_test


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TEST_CLIENT_SCRIPT = SCRIPTS_DIR / "test_mcp_client.py"


def test_mcp_client_e2e_mock_runner():
    """Verify that the mock MCP client runs all tool calls via asyncio over stdio JSON-RPC."""
    results = asyncio.run(run_mcp_client_test())
    
    assert "tools" in results
    assert "trace" in results
    assert "contract" in results
    assert "breakage" in results

    # Verify tool discovery
    assert "trace_fullstack_path" in results["tools"]
    assert "get_route_contract" in results["tools"]
    assert "verify_breakage" in results["tools"]

    # Verify trace result
    trace = results["trace"]
    assert trace.get("found") is True
    assert trace.get("target") == "backend/models.py::BillingAccount"
    assert "backend/models.py" in trace.get("impacted_files", [])

    # Verify contract result
    contract = results["contract"]
    assert contract.get("found") is True
    assert contract.get("route_path") == "/api/v1/users/{user_id}/billing"
    assert contract.get("handler_name") == "get_user_billing"
    assert len(contract.get("linked_callers", [])) >= 1

    # Verify breakage result
    breakage = results["breakage"]
    assert breakage.get("has_breakage") is False
    assert breakage.get("error_count") == 0


def test_mcp_client_script_subprocess_execution():
    """Verify scripts/test_mcp_client.py executes standalone with exit code 0."""
    result = subprocess.run(
        [sys.executable, str(TEST_CLIENT_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}"
    assert "Starting StackBridge Mock MCP Client Test" in result.stdout
    assert "ALL MOCK MCP CLIENT TESTS PASSED SUCCESSFULLY!" in result.stdout
