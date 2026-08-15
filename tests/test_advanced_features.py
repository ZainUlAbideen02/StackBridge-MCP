"""Integration tests for nested sub-routers, React Query parsing, and StackGuardEngine."""

from pathlib import Path
import pytest

from stackbridge.core.graph import StackGraph
from stackbridge.parsers.py_route_parser import PythonRouteParser
from stackbridge.parsers.ts_fetch_parser import extract_nextjs_fetches
from stackbridge.verifier.guard import StackGuardEngine


ADVANCED_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "advanced_fullstack"
SYNTHETIC_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"


def test_subrouter_prefix_resolution_concatenation():
    """Verify sub-router prefix resolution concatenating /api/v2 with /analytics/{org_id}."""
    # Test static resolver helper
    resolved_path = PythonRouteParser.resolve_subrouter_prefix("/api/v2", "/analytics/{org_id}")
    assert resolved_path == "/api/v2/analytics/{org_id}"

    resolved_auth = PythonRouteParser.resolve_subrouter_prefix("/api/v2", "/auth/login")
    assert resolved_auth == "/api/v2/auth/login"

    # Test full repo graph resolution across app.py and routers/
    graph = StackGraph.build_from_repo(str(ADVANCED_FIXTURES_DIR))
    assert graph.node_count > 0

    route_paths = [r.normalized_path for r in graph.backend_routes.values()]
    assert "/api/v2/analytics/{org_id}" in route_paths
    assert "/api/v2/auth/login" in route_paths


def test_extract_nextjs_fetches_react_query_and_apiclient():
    """Verify extract_nextjs_fetches correctly parses apiClient within useQuery and axios calls."""
    dashboard_file = ADVANCED_FIXTURES_DIR / "frontend" / "Dashboard.tsx"
    assert dashboard_file.exists()

    with open(dashboard_file, "r", encoding="utf-8") as f:
        code = f.read()

    fetches = extract_nextjs_fetches(code, file_path="frontend/Dashboard.tsx")
    assert len(fetches) >= 2

    # Verify apiClient inside useQuery
    analytics_call = next((f for f in fetches if "/analytics" in f.normalized_pattern), None)
    assert analytics_call is not None
    assert analytics_call.normalized_pattern == "/api/v2/analytics/{orgId}"
    assert analytics_call.http_method == "GET"
    assert analytics_call.is_template is True
    assert "orgId" in analytics_call.path_params

    # Verify axios.post call
    auth_call = next((f for f in fetches if "/auth/login" in f.normalized_pattern), None)
    assert auth_call is not None
    assert auth_call.normalized_pattern == "/api/v2/auth/login"
    assert auth_call.http_method == "POST"
    assert auth_call.is_template is False


def test_stack_guard_clean_repository():
    """Verify StackGuardEngine runs cleanly on valid advanced fullstack repository."""
    guard = StackGuardEngine(repo_path=str(ADVANCED_FIXTURES_DIR))
    report = guard.check_repo()

    assert report.has_breakage is False
    assert report.error_count == 0
    assert len(report.unmatched_frontend_calls) == 0
    assert report.total_frontend_calls >= 2
    assert report.total_backend_routes >= 2


def test_stack_guard_detects_cross_boundary_breakage():
    """Verify StackGuardEngine detects cross-boundary breakage when backend schema or routes break."""
    guard = StackGuardEngine(repo_path=str(SYNTHETIC_FIXTURES_DIR))

    # Simulate breaking change in backend model
    models_path = SYNTHETIC_FIXTURES_DIR / "backend" / "models.py"
    with open(models_path, "r", encoding="utf-8") as f:
        original_code = f.read()

    modified_code = original_code.replace(
        'plan = Column(String, nullable=False, default="free")',
        '# plan column removed'
    )

    report = guard.verify_impacted_files(
        modified_files={"backend/models.py": modified_code},
        repo_path=SYNTHETIC_FIXTURES_DIR,
    )

    assert report.has_breakage is True
    assert report.error_count > 0
    assert len(report.impacted_files) > 0


def test_stack_guard_detects_unmatched_frontend_endpoint():
    """Verify StackGuardEngine detects frontend fetch calls that do not match backend routes."""
    guard = StackGuardEngine(repo_path=str(ADVANCED_FIXTURES_DIR))

    broken_frontend = """
    export const BrokenComponent = () => {
        const load = () => fetch('/api/v2/non_existent_endpoint');
        return <button onClick={load}>Click</button>;
    };
    """

    # Run checker with unknown route
    diags = guard.verifier_engine.ts_verifier.check_code(
        target_code=broken_frontend,
        target_file_path="frontend/Broken.tsx",
        known_routes={"/api/v2/analytics/{org_id}", "/api/v2/auth/login"},
    )

    assert len(diags) > 0
    assert any("does not match any registered backend route" in d.message for d in diags)
