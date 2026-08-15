"""HTTP Server and endpoint handlers for StackBridge Web Visualizer."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse

from stackbridge.core.graph import StackGraph


TEMPLATE_PATH = Path(__file__).parent / "template.html"


def get_ui_html() -> str:
    """Loads and returns the HTML template for the web visualizer."""
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Visualizer template not found at {TEMPLATE_PATH}")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def get_graph_data(repo_path: Union[str, Path]) -> Dict[str, Any]:
    """Builds the full-stack dependency graph and returns node, edge, and metric payloads."""
    graph = StackGraph.build_from_repo(str(repo_path))
    raw_dict = graph.to_dict()

    return {
        "nodes": raw_dict.get("nodes", []),
        "edges": raw_dict.get("edges", []),
        "metrics": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "frontend_calls": len(graph.frontend_calls),
            "backend_routes": len(graph.backend_routes),
            "orm_models": len(graph.orm_models),
        },
    }


def get_blast_radius_data(repo_path: Union[str, Path], node_id: str) -> Dict[str, Any]:
    """Calculates and returns downstream/upstream blast radius for a given node ID."""
    graph = StackGraph.build_from_repo(str(repo_path))
    return graph.get_blast_radius(node_id)


def handle_ui_request(path_with_query: str, repo_path: Union[str, Path]) -> Tuple[int, str, bytes]:
    """Handles an incoming HTTP request path and returns (status_code, content_type, body_bytes)."""
    parsed = urlparse(path_with_query)
    path = parsed.path
    query_params = parse_qs(parsed.query)

    if path in ("", "/"):
        html = get_ui_html()
        return 200, "text/html; charset=utf-8", html.encode("utf-8")

    elif path == "/api/graph":
        data = get_graph_data(repo_path)
        return 200, "application/json", json.dumps(data).encode("utf-8")

    elif path == "/api/blast-radius":
        node_id_list = query_params.get("node_id", [""])
        node_id = node_id_list[0] if node_id_list else ""
        data = get_blast_radius_data(repo_path, node_id)
        return 200, "application/json", json.dumps(data).encode("utf-8")

    else:
        err = {"error": "Not Found", "path": path}
        return 404, "application/json", json.dumps(err).encode("utf-8")


class StackBridgeUIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler dispatching Web Visualizer routes."""

    repo_path: Path = Path.cwd()

    def do_GET(self) -> None:
        status, content_type, body = handle_ui_request(self.path, self.repo_path)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard request logging in test/CLI environments
        pass


def create_ui_server(
    repo_path: Union[str, Path] = ".",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> HTTPServer:
    """Factory creating an HTTPServer configured with StackBridge visualizer routes."""
    resolved_repo = Path(repo_path).resolve()

    class BoundHandler(StackBridgeUIRequestHandler):
        repo_path = resolved_repo

    return HTTPServer((host, port), BoundHandler)
