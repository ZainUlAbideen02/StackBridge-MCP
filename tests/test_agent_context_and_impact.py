"""Unit tests for AgentContextGenerator and TestImpactSelector."""

import os
from pathlib import Path
import pytest

from stackbridge.core.agent_context import AgentContextGenerator
from stackbridge.core.graph import StackGraph
from stackbridge.core.models import BackendRoute, EndpointParam, FrontendEndpointCall, HttpMethod, ORMModel
from stackbridge.core.test_impact import TestImpactSelector


REPO_ROOT = Path(__file__).parent.parent
SYNTHETIC_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_fullstack"
ADVANCED_DIR = REPO_ROOT / "tests" / "fixtures" / "advanced_fullstack"


def test_agent_context_generator_markdown_output():
    """Verifies that AgentContextGenerator builds complete, structured AGENTS.md content."""
    graph = StackGraph.build_from_repo(str(SYNTHETIC_DIR))
    md = AgentContextGenerator.generate_agents_md(graph, repo_path=str(SYNTHETIC_DIR))

    assert "# AGENTS.md — StackBridge AI Agent Architecture Guide" in md
    assert "## 1. System Topology Overview" in md
    assert "## 2. Full-Stack Boundary & Route Matrix" in md
    assert "## 3. Database Schema & ORM Models" in md
    assert "## 4. MCP Server Tools for Coding Agents" in md
    assert "## 5. Agent Safety Guidelines & Guard Rules" in md

    # Check route entries
    assert "get_user_billing" in md or "/api/v1/billing" in md
    # Check model entries
    assert "BillingAccount" in md or "User" in md


def test_agent_context_generator_writes_file(tmp_path):
    """Verifies that AgentContextGenerator writes AGENTS.md to disk correctly."""
    graph = StackGraph.build_from_repo(str(SYNTHETIC_DIR))
    out_file = tmp_path / "subdir" / "AGENTS.md"

    written = AgentContextGenerator.write_agents_md(
        repo_path=str(SYNTHETIC_DIR),
        output_path=out_file,
        graph=graph,
    )

    assert Path(written).exists()
    content = Path(written).read_text(encoding="utf-8")
    assert "StackBridge AI Agent Architecture Guide" in content
    assert len(content) > 200


def test_test_impact_selector_discovers_tests():
    """Verifies discovery of Python and TypeScript test files."""
    selector = TestImpactSelector(repo_path=str(REPO_ROOT))
    tests = selector.discover_tests()

    assert len(tests) > 0
    # Must contain test_route_matcher, test_mcp_server, etc.
    assert any("test_route_matcher.py" in t for t in tests)
    assert any("test_mcp_server.py" in t for t in tests)
    # Must not contain ignored virtualenvs or caches
    assert not any(".venv" in t for t in tests)
    assert not any("__pycache__" in t for t in tests)


def test_test_impact_selector_maps_routes_to_tests():
    """Verifies accurate mapping of backend routes to their corresponding test callers."""
    graph = StackGraph.build_from_repo(str(REPO_ROOT))
    selector = TestImpactSelector(repo_path=str(REPO_ROOT), graph=graph)

    route_to_tests = selector.map_tests_to_routes()
    assert isinstance(route_to_tests, dict)
    assert len(route_to_tests) > 0

    # Test that synthetic billing route has corresponding test callers
    billing_route_key = None
    for r_id in route_to_tests:
        if "get_user_billing" in r_id:
            billing_route_key = r_id
            break

    if billing_route_key:
        callers = route_to_tests[billing_route_key]
        assert len(callers) > 0
        # synthetic route is tested in test_route_matcher or test_mcp_client_e2e
        assert any("test_route_matcher.py" in c or "test_mcp" in c or "test_advanced" in c for c in callers)


def test_test_impact_selector_identifies_impacted_tests():
    """Verifies that modifying specific backend files returns the exact test files impacted."""
    graph = StackGraph.build_from_repo(str(REPO_ROOT))
    selector = TestImpactSelector(repo_path=str(REPO_ROOT), graph=graph)

    # When synthetic routes.py is modified
    impacted = selector.get_impacted_tests(["tests/fixtures/synthetic_fullstack/backend/routes.py"])
    assert len(impacted) > 0
    assert any("test_route_matcher.py" in t or "test_mcp" in t for t in impacted)

    # When a test file itself is modified
    test_mod = ["tests/test_agent_formatter.py"]
    impacted_test = selector.get_impacted_tests(test_mod)
    assert any("test_agent_formatter.py" in t for t in impacted_test)


def test_test_impact_selector_generates_report():
    """Verifies that generate_impact_report creates a comprehensive summary with coverage ratio."""
    graph = StackGraph.build_from_repo(str(REPO_ROOT))
    selector = TestImpactSelector(repo_path=str(REPO_ROOT), graph=graph)

    report = selector.generate_impact_report(["tests/fixtures/synthetic_fullstack/backend/models.py"])
    assert "modified_files" in report
    assert "impacted_tests" in report
    assert "untested_routes" in report
    assert "total_routes" in report
    assert "coverage_ratio" in report
    assert 0.0 <= report["coverage_ratio"] <= 1.0
    assert report["total_routes"] > 0
