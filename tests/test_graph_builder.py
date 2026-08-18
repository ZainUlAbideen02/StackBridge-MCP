"""Tests for SQLAlchemy parser, StackGraph unified repo builder, blast radius analysis, and caching."""

from pathlib import Path

from stackbridge.core.graph import StackGraph
from stackbridge.parsers.sqlalchemy_parser import SQLAlchemyParser, extract_sqlalchemy_models

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"
MODELS_FIXTURE = FIXTURES_DIR / "backend" / "models.py"


def test_sqlalchemy_parser_extraction():
    parser = SQLAlchemyParser()
    assert MODELS_FIXTURE.exists(), f"Models fixture not found at {MODELS_FIXTURE}"
    models = parser.parse_file(str(MODELS_FIXTURE))

    assert len(models) == 2
    model_names = [m.class_name for m in models]
    assert "User" in model_names
    assert "BillingAccount" in model_names

    user_model = next(m for m in models if m.class_name == "User")
    assert user_model.table_name == "users"
    user_field_names = [f.name for f in user_model.fields]
    assert "id" in user_field_names
    assert "email" in user_field_names
    assert "name" in user_field_names
    assert "BillingAccount" in user_model.relationships

    billing_model = next(m for m in models if m.class_name == "BillingAccount")
    assert billing_model.table_name == "billing_accounts"
    billing_field_names = [f.name for f in billing_model.fields]
    assert "id" in billing_field_names
    assert "user_id" in billing_field_names
    assert "plan" in billing_field_names
    assert "balance" in billing_field_names
    assert "User" in billing_model.relationships


def test_extract_sqlalchemy_models_standalone():
    assert MODELS_FIXTURE.exists(), f"Models fixture not found at {MODELS_FIXTURE}"
    with open(MODELS_FIXTURE, "r", encoding="utf-8") as f:
        code = f.read()

    models = extract_sqlalchemy_models(code, str(MODELS_FIXTURE))
    assert len(models) == 2
    class_names = [m.class_name for m in models]
    assert "User" in class_names
    assert "BillingAccount" in class_names

    user_info = next(m for m in models if m.class_name == "User")
    assert user_info.table_name == "users"
    assert any(f.name == "email" for f in user_info.fields)

    billing_info = next(m for m in models if m.class_name == "BillingAccount")
    assert billing_info.table_name == "billing_accounts"
    assert any(f.name == "plan" for f in billing_info.fields)


def test_stack_graph_build_from_repo():
    sg = StackGraph.build_from_repo(str(FIXTURES_DIR))

    # Verify Frontend, Route, and Model node types exist
    node_types = set(d.get("type") for _, d in sg.graph.nodes(data=True))
    assert "frontend" in node_types
    assert "route" in node_types
    assert "model" in node_types

    # Verify specific nodes: UserProfile.tsx, /api/v1/users/{user_id}/billing (get_user_billing), BillingAccount, User
    assert any("UserProfile.tsx" in n for n in sg.graph.nodes)
    assert any("get_user_billing" in n or "/api/v1/users/{user_id}/billing" in str(d) for n, d in sg.graph.nodes(data=True))
    assert any("BillingAccount" in n for n in sg.graph.nodes)
    assert any("User" in n for n in sg.graph.nodes)

    # Verify cross-boundary edge between UserProfile.tsx and /api/v1/users/{user_id}/billing route with confidence 0.88
    matching_edges = [
        (u, v, d) for u, v, d in sg.graph.edges(data=True)
        if "UserProfile.tsx" in u and "get_user_billing" in v
    ]
    assert len(matching_edges) == 1
    src, tgt, edge_data = matching_edges[0]
    assert edge_data["confidence"] == 0.88
    assert edge_data["relation"] == "calls"
    assert edge_data["param_mappings"] == {"userId": "user_id"}

    # Static teams edge check
    teams_edges = [
        (u, v, d) for u, v, d in sg.graph.edges(data=True)
        if "UserProfile.tsx" in u and "get_teams" in v
    ]
    assert len(teams_edges) == 1
    _, _, teams_edge_data = teams_edges[0]
    assert teams_edge_data["confidence"] == 1.0


def test_blast_radius_traversal():
    sg = StackGraph.build_from_repo(str(FIXTURES_DIR))

    blast = sg.get_blast_radius("backend/models.py::BillingAccount")
    assert blast["found"] is True
    assert blast["target"] == "backend/models.py::BillingAccount"

    # Traces upstream to UserProfile.tsx
    assert "frontend/UserProfile.tsx" in blast["affected_files"]
    assert any("UserProfile.tsx" in n for n in blast["affected_nodes"])
    assert any("get_user_billing" in n for n in blast["affected_nodes"])

    # Check affected frontend list
    assert len(blast["affected_frontend"]) >= 1
    assert any("UserProfile.tsx" in fe["file_path"] for fe in blast["affected_frontend"])

    # Check path trace from BillingAccount -> get_user_billing -> UserProfile.tsx
    found_trace = False
    for p in blast["paths"]:
        if len(p) == 3 and "BillingAccount" in p[0] and "get_user_billing" in p[1] and "UserProfile.tsx" in p[2]:
            found_trace = True
            break
    assert found_trace is True


def test_json_export_and_caching(tmp_path):
    sg = StackGraph.build_from_repo(str(FIXTURES_DIR))

    # Test JSON serialization
    json_str = sg.to_json()
    assert '"version": "1.0.0"' in json_str
    assert "BillingAccount" in json_str
    assert "UserProfile.tsx" in json_str

    # Test load from JSON string
    sg_restored = StackGraph.from_json(json_str)
    assert len(sg_restored.graph.nodes) == len(sg.graph.nodes)
    assert len(sg_restored.graph.edges) == len(sg.graph.edges)

    # Test file export and load
    export_file = tmp_path / ".stackbridge" / "graph.json"
    sg.export_json(export_file)
    assert export_file.exists()

    sg_file_loaded = StackGraph.load_json(export_file)
    assert len(sg_file_loaded.graph.nodes) == len(sg.graph.nodes)

    # Test cache saving and loading in .stackbridge/graph.json
    cache_file = tmp_path / ".stackbridge" / "graph.json"
    sg.save_cache(cache_file)
    assert cache_file.exists()

    sg_cached = StackGraph.load_cache(cache_file)
    assert sg_cached is not None
    assert len(sg_cached.graph.nodes) == len(sg.graph.nodes)
