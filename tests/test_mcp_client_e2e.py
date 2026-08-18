"""End-to-end tests for StackBridge MCP Server using the Mock MCP Client."""

import subprocess
import sys
from pathlib import Path

from scripts.test_mcp_client import run_mock_client_test

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TEST_CLIENT_SCRIPT = SCRIPTS_DIR / "test_mcp_client.py"


def test_mcp_client_e2e_runner():
    """Verify that the mock MCP client executes JSON-RPC 2.0 lifecycle over stdio successfully."""
    results = run_mock_client_test()

    assert "initialize" in results
    assert "tools" in results
    assert "trace" in results
    assert "health" in results

    # Verify tool discovery
    assert "trace_fullstack_path" in results["tools"]
    assert "verify_schema_change" in results["tools"]
    assert "get_route_contract" in results["tools"]
    assert "get_stack_health" in results["tools"]

    # Verify trace result contains matched frontend components
    trace = results["trace"]
    if isinstance(trace, dict):
        assert trace.get("found") is True
        assert len(trace.get("matched_frontend_components", [])) >= 1 or len(trace.get("chains", [])) >= 1

    # Verify health stats
    health = results["health"]
    assert health.get("status") in ("healthy", "degraded")
    assert health.get("total_nodes", 0) > 0


def test_mcp_client_script_subprocess_execution():
    """Verify scripts/test_mcp_client.py executes standalone as a subprocess with exit code 0."""
    result = subprocess.run(
        [sys.executable, str(TEST_CLIENT_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Script failed with stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "Starting StackBridge Mock MCP Client Automated E2E Test" in result.stdout
    assert "ALL MOCK MCP CLIENT TESTS PASSED SUCCESSFULLY (Exit Code 0)!" in result.stdout
