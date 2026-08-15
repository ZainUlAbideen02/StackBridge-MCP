"""Tests for StackBridge Web Visualizer server, template, and API endpoints."""

import json
from pathlib import Path
import threading
import time
from urllib.request import urlopen
import pytest

from stackbridge.ui.server import (
    create_ui_server,
    get_blast_radius_data,
    get_graph_data,
    get_ui_html,
    handle_ui_request,
)


SYNTHETIC_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"
TEMPLATE_FILE = Path(__file__).parent.parent / "stackbridge" / "ui" / "template.html"


def test_ui_template_file_exists_and_is_valid():
    """Verify stackbridge/ui/template.html exists and contains valid HTML markup."""
    assert TEMPLATE_FILE.exists(), f"Expected {TEMPLATE_FILE} to exist"

    html = get_ui_html()
    assert len(html) > 100
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "StackBridge" in html
    assert "</canvas>" in html or "<canvas" in html
    assert "</html>" in html


def test_api_graph_endpoint_data():
    """Verify /api/graph returns valid JSON with nodes, edges, and metrics."""
    data = get_graph_data(SYNTHETIC_FIXTURES_DIR)

    assert "nodes" in data
    assert "edges" in data
    assert "metrics" in data

    assert len(data["nodes"]) >= 6
    assert len(data["edges"]) >= 5

    metrics = data["metrics"]
    assert metrics["nodes"] >= 6
    assert metrics["edges"] >= 5
    assert metrics["frontend_calls"] >= 1
    assert metrics["backend_routes"] >= 1
    assert metrics["orm_models"] >= 1

    # Test via request handler directly
    status, content_type, body = handle_ui_request("/api/graph", SYNTHETIC_FIXTURES_DIR)
    assert status == 200
    assert "application/json" in content_type
    parsed_json = json.loads(body.decode("utf-8"))
    assert parsed_json["metrics"]["nodes"] >= 6


def test_api_blast_radius_endpoint_data():
    """Verify /api/blast-radius?node_id=... returns expected blast radius subgraph."""
    target_node = "backend/models.py::BillingAccount"
    blast_data = get_blast_radius_data(SYNTHETIC_FIXTURES_DIR, target_node)

    assert blast_data.get("found") is True
    assert len(blast_data.get("affected_nodes", [])) > 0
    assert len(blast_data.get("affected_files", [])) > 0
    assert any("routes.py" in f for f in blast_data["affected_files"])

    # Test via request handler with query string
    status, content_type, body = handle_ui_request(
        f"/api/blast-radius?node_id={target_node}",
        SYNTHETIC_FIXTURES_DIR,
    )
    assert status == 200
    assert "application/json" in content_type
    parsed_json = json.loads(body.decode("utf-8"))
    assert parsed_json.get("found") is True
    assert len(parsed_json.get("affected_nodes", [])) > 0


def test_live_ui_server_http_lifecycle():
    """Verify live HTTPServer serves HTML, /api/graph, and /api/blast-radius over localhost."""
    # Find free local port
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = create_ui_server(repo_path=SYNTHETIC_FIXTURES_DIR, host="127.0.0.1", port=port)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.1)

    base_url = f"http://127.0.0.1:{port}"

    try:
        # Test root / HTML
        with urlopen(f"{base_url}/") as res:
            assert res.status == 200
            content = res.read().decode("utf-8")
            assert "<!DOCTYPE html>" in content

        # Test /api/graph
        with urlopen(f"{base_url}/api/graph") as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert data["metrics"]["nodes"] >= 6

        # Test /api/blast-radius
        with urlopen(f"{base_url}/api/blast-radius?node_id=backend/models.py::BillingAccount") as res:
            assert res.status == 200
            data = json.loads(res.read().decode("utf-8"))
            assert data["found"] is True
    finally:
        server.shutdown()
        server.server_close()
