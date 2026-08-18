"""Edge-case and hardening tests for StackBridge-MCP v0.1.0."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stackbridge.core.graph import StackGraph
from stackbridge.core.models import BackendRoute, HttpMethod
from stackbridge.parsers.py_route_parser import PythonRouteParser
from stackbridge.verifier.engine import VerifierEngine

REPO_ROOT = Path(__file__).parent.parent
SYNTHETIC_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_fullstack"


def test_multi_decorator_route_extraction():
    """Verifies that routes wrapped with multiple decorators (auth, rate-limiter, custom) are accurately extracted."""
    code = """
from fastapi import APIRouter
router = APIRouter(prefix="/api/v1")

def require_auth(scope: str):
    def decorator(fn):
        return fn
    return decorator

def rate_limit(rate: str):
    def decorator(fn):
        return fn
    return decorator

@rate_limit("100/minute")
@require_auth("admin:metrics")
@router.get("/metrics/{cluster_id}", response_model=MetricsResponse)
def get_cluster_metrics(cluster_id: str):
    return {"cluster_id": cluster_id}

@require_auth("user:read")
@rate_limit("50/minute")
@router.post("/export")
def export_data():
    pass
"""
    parser = PythonRouteParser()
    routes = parser.parse_code(code, file_path="backend/metrics.py")

    assert len(routes) == 2
    metrics_route = next((r for r in routes if r.function_name == "get_cluster_metrics"), None)
    export_route = next((r for r in routes if r.function_name == "export_data"), None)

    assert metrics_route is not None
    assert metrics_route.raw_path == "/api/v1/metrics/{cluster_id}"
    assert metrics_route.http_methods == [HttpMethod.GET]
    assert len(metrics_route.path_params) == 1
    assert metrics_route.path_params[0].name == "cluster_id"

    assert export_route is not None
    assert export_route.raw_path == "/api/v1/export"
    assert export_route.http_methods == [HttpMethod.POST]


def test_windows_backslash_normalization_in_graph_nodes():
    """Verifies that all node keys, file paths, and edges use POSIX forward slashes regardless of input backslashes."""
    graph = StackGraph()

    # Add frontend call with Windows backslashes
    from stackbridge.core.models import FrontendEndpointCall, ORMField, ORMModel
    fe_call = FrontendEndpointCall(
        file_path="frontend\\components\\UserProfile.tsx",
        line_number=42,
        raw_url="/api/v1/users/123",
        normalized_path="/api/v1/users/123",
        http_method=HttpMethod.GET,
    )
    fe_id = graph.add_frontend_call(fe_call)
    assert "\\" not in fe_id
    assert "frontend/components/UserProfile.tsx::fetch::42" == fe_id

    # Add backend route with Windows backslashes
    be_route = BackendRoute(
        file_path="backend\\routes\\user_routes.py",
        line_number=15,
        function_name="get_user",
        raw_path="/api/v1/users/{id}",
        normalized_path="/api/v1/users/{id}",
        http_methods=[HttpMethod.GET],
    )
    be_id = graph.add_backend_route(be_route)
    assert "\\" not in be_id
    assert "backend/routes/user_routes.py::get_user" == be_id

    # Add ORM model with Windows backslashes
    model = ORMModel(
        file_path="backend\\models\\user.py",
        line_number=10,
        class_name="User",
        table_name="users",
        fields=[ORMField(name="id", data_type="Integer")],
    )
    m_id = graph.add_orm_model(model)
    assert "\\" not in m_id
    assert "backend/models/user.py::User" == m_id

    # Check serialized dictionary nodes
    d = graph.to_dict()
    for n in d["nodes"]:
        assert "\\" not in n["id"]
        assert "\\" not in n["file_path"]


def test_verifier_concurrency_safety():
    """Verifies that VerifierEngine handles concurrent requests from multiple agent threads safely without race conditions."""
    engine = VerifierEngine(repo_path=SYNTHETIC_DIR, timeout_seconds=5.0)
    graph = StackGraph.build_from_repo(str(SYNTHETIC_DIR))

    # Baseline files content
    routes_file = SYNTHETIC_DIR / "backend" / "routes.py"
    routes_content = routes_file.read_text(encoding="utf-8")

    # Modified content simulation
    mod_1 = {"backend/routes.py": routes_content + "\n# thread 1 modification\n"}
    mod_2 = {"backend/routes.py": routes_content + "\n# thread 2 modification\n"}

    def _verify_thread(mod_dict):
        report = engine.verify_impacted_files(
            modified_files=mod_dict,
            repo_path=SYNTHETIC_DIR,
            graph=graph,
        )
        return report

    # Concurrently execute 8 verifications across worker threads
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_verify_thread, mod_1 if i % 2 == 0 else mod_2) for i in range(8)]
        results = [f.result() for f in futures]

    assert len(results) == 8
    for r in results:
        assert isinstance(r.has_breakage, bool)
        assert isinstance(r.diagnostics, list)
        assert len(r.verified_files) > 0
