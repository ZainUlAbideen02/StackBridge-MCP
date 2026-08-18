"""Enterprise scale and SQLite CTE traversal test suite for StackBridge-MCP."""

import os
from pathlib import Path

from stackbridge.core.config import StackBridgeConfig
from stackbridge.core.git_delta import GitDeltaIndexer
from stackbridge.core.graph import StackGraph
from stackbridge.core.models import BackendRoute, FrontendEndpointCall, HttpMethod, ORMField, ORMModel
from stackbridge.core.sqlite_store import SQLiteStore
from stackbridge.verifier.agent_formatter import AgentDiagnosticFormatter
from stackbridge.verifier.py_checker import DiagnosticError

REPO_ROOT = Path(__file__).parent.parent
SYNTHETIC_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_fullstack"


def test_sqlite_store_schema_and_graph_roundtrip(tmp_path):
    """Verifies SQLiteStore table creation, graph insertion, and reconstruction."""
    db_file = tmp_path / "graph.db"
    store = SQLiteStore(db_file)
    assert db_file.exists()

    # Create synthetic test graph
    graph = StackGraph()
    fe_call = FrontendEndpointCall(
        file_path="frontend/UserProfile.tsx",
        line_number=25,
        raw_url="/api/v1/users/123/billing",
        normalized_path="/api/v1/users/{user_id}/billing",
        http_method=HttpMethod.GET,
    )
    fe_id = graph.add_frontend_call(fe_call)

    route = BackendRoute(
        file_path="backend/routes.py",
        line_number=10,
        function_name="get_user_billing",
        raw_path="/api/v1/users/{user_id}/billing",
        normalized_path="/api/v1/users/{user_id}/billing",
        http_methods=[HttpMethod.GET],
    )
    route_id = graph.add_backend_route(route)

    model = ORMModel(
        file_path="backend/models.py",
        line_number=12,
        class_name="BillingAccount",
        table_name="billing_accounts",
        fields=[ORMField(name="id", data_type="Integer"), ORMField(name="balance", data_type="Float")],
    )
    model_id = graph.add_orm_model(model)

    graph.link_frontend_to_route(fe_id, route_id, confidence=1.0, is_exact=True, param_mappings={})
    graph.link_route_to_model(route_id, model_id)

    # Save to SQLite
    store.save_graph(graph)

    # Load from SQLite
    loaded_graph = store.load_graph()
    assert loaded_graph.node_count == 3
    assert loaded_graph.edge_count == 2
    assert fe_id in loaded_graph.graph.nodes
    assert route_id in loaded_graph.graph.nodes
    assert model_id in loaded_graph.graph.nodes


def test_sqlite_recursive_cte_blast_radius(tmp_path):
    """Verifies SQLite recursive CTE executes fast transitive blast-radius queries across all boundaries."""
    db_file = tmp_path / "graph.db"
    store = SQLiteStore(db_file)

    graph = StackGraph.build_from_repo(str(SYNTHETIC_DIR))
    store.save_graph(graph)

    target = "backend/models.py::BillingAccount"
    result = store.recursive_cte_blast_radius(target, max_depth=5)

    assert result["found"] is True
    assert result["traversal_engine"] == "sqlite_recursive_cte"
    assert len(result["affected_nodes"]) > 0
    assert len(result["affected_files"]) > 0
    assert any("routes.py" in f for f in result["affected_files"])
    assert any("UserProfile.tsx" in f for f in result["affected_files"])
    assert len(result["paths"]) > 0


def test_git_delta_indexer_changed_files_discovery():
    """Verifies GitDeltaIndexer discovers modified files in git repository without rescanning entire tree."""
    indexer = GitDeltaIndexer(REPO_ROOT)
    changed = indexer.get_changed_files()
    assert isinstance(changed, list)
    # Check that changed files are normalized relative paths
    for f in changed:
        assert "\\" not in f
        assert not os.path.isabs(f)


def test_business_criticality_rules_and_diagnostic_ranking(tmp_path):
    """Verifies StackBridgeConfig critical path matching and AgentDiagnosticFormatter priority boost."""
    config_file = tmp_path / "stackbridge.yaml"
    config_file.write_text(
        """
critical_paths:
  - "auth/**"
  - "billing/**"
  - "payments/**"
ignored_paths:
  - "**/*.tmp"
""",
        encoding="utf-8",
    )

    cfg = StackBridgeConfig(repo_path=tmp_path)
    assert cfg.is_critical_path("billing/models.py") is True
    assert cfg.is_critical_path("auth/router.py") is True
    assert cfg.is_critical_path("users/profile.py") is False

    # Check diagnostic ranking
    normal_diag = DiagnosticError(
        file_path="users/profile.py",
        line=10,
        message="Minor field rename",
        severity="error",
        rule="schema-drift",
    )
    critical_diag = DiagnosticError(
        file_path="billing/models.py",
        line=45,
        message="Dropped column 'balance' on BillingAccount",
        severity="error",
        rule="schema-attribute-missing",
    )

    report = AgentDiagnosticFormatter.format_breakage_report(
        diagnostics=[normal_diag, critical_diag],
        repo_path=str(tmp_path),
    )

    assert "🚨 CRITICAL BREAKING" in report
    assert "🚨 **[CRITICAL PATH]**" in report
    # Critical error should appear before normal error in the formatted report
    crit_pos = report.find("billing/models.py")
    norm_pos = report.find("users/profile.py")
    assert crit_pos < norm_pos
