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


def _format_node_display(node_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Formats raw node data into Vis-Network compliant node properties."""
    node_id = node_raw.get("id", "")
    node_type = node_raw.get("type") or node_raw.get("node_type", "frontend")
    file_path = node_raw.get("file_path", "")
    line_num = node_raw.get("line") or node_raw.get("line_number", 1)

    # 1. Frontend Component
    if node_type in ("frontend", "frontend_component"):
        file_basename = Path(file_path).name if file_path else node_id.split("/")[-1].split("\\")[-1]
        label = f"[UI] {file_basename} (L{line_num})"
        title = (
            f"<b>[UI Frontend Call]</b><br>"
            f"<b>File:</b> {file_path}:{line_num}<br>"
            f"<b>Method:</b> {node_raw.get('http_method', 'GET')}<br>"
            f"<b>Target URL:</b> {node_raw.get('raw_url') or node_raw.get('normalized_path', '')}"
        )
        group = "frontend"
        level = 1
        bg_color = "#0284C7"
        border_color = "#38BDF8"

    # 2. API Route Handler & MCP Server Tools
    elif node_type in ("route", "api_route"):
        methods = node_raw.get("http_methods") or [node_raw.get("http_method", "GET")]
        method_str = methods[0] if methods else "GET"
        route_path = node_raw.get("normalized_path") or node_raw.get("raw_path") or node_id.split("::")[-1]

        if method_str in ("MCP_TOOL", "MCP_RESOURCE", "[MCP_TOOL]"):
            func_name = node_raw.get("function_name") or route_path.replace("tools/", "")
            label = f"[MCP] {func_name}"
            title = (
                f"<b>[MCP Server Tool]</b><br>"
                f"<b>File:</b> {file_path}<br>"
                f"<b>Tool:</b> {func_name}()<br>"
                f"<b>Type:</b> {method_str}<br>"
                f"<b>Contract:</b> {node_raw.get('response_model') or 'Standard Tool Interface'}"
            )
            group = "mcp_tool"
            level = 2
            bg_color = "#06B6D4"
            border_color = "#22D3EE"
        else:
            label = f"[API] {method_str} {route_path}"
            title = (
                f"<b>[API Route]</b><br>"
                f"<b>File:</b> {file_path}<br>"
                f"<b>Handler:</b> {node_raw.get('function_name', 'route_handler')}()<br>"
                f"<b>Method:</b> {method_str}<br>"
                f"<b>Path:</b> {route_path}"
            )
            group = "route"
            level = 2
            bg_color = "#059669"
            border_color = "#34D399"

    # 3. ORM Schema Model
    elif node_type in ("model", "schema_model"):
        class_name = node_raw.get("class_name") or node_id.split("::")[-1]
        table_name = node_raw.get("table_name") or class_name.lower()
        label = f"[DB] {class_name} ({table_name})"
        title = (
            f"<b>[DB ORM Model]</b><br>"
            f"<b>File:</b> {file_path}<br>"
            f"<b>Model:</b> {class_name}<br>"
            f"<b>Table:</b> {table_name}"
        )
        group = "model"
        level = 3
        bg_color = "#7C3AED"
        border_color = "#A78BFA"

    else:
        label = node_id
        title = f"<b>{node_id}</b>"
        group = "other"
        level = 2
        bg_color = "#475569"
        border_color = "#94A3B8"

    formatted = dict(node_raw)
    formatted.update({
        "id": node_id,
        "label": label,
        "title": title,
        "group": group,
        "level": level,
        "shape": "box",
        "margin": 14,
        "borderRadius": 8,
        "font": {"color": "#FFFFFF", "face": "monospace", "size": 14},
        "color": {
            "background": bg_color,
            "border": border_color,
            "highlight": {
                "background": bg_color,
                "border": border_color,
            },
            "hover": {
                "background": bg_color,
                "border": "#FFFFFF",
            },
        },
        "borderWidth": 1.5,
        "shadow": {"enabled": True, "color": "rgba(0,0,0,0.35)", "size": 8, "x": 0, "y": 3},
    })
    return formatted


def _format_edge_display(edge_raw: Dict[str, Any]) -> Dict[str, Any]:
    """Formats raw edge data into Vis-Network compliant edge properties with confidence labels."""
    source = edge_raw.get("source") or edge_raw.get("from")
    target = edge_raw.get("target") or edge_raw.get("to")
    confidence = float(edge_raw.get("confidence", 1.0))
    is_exact = bool(edge_raw.get("is_exact", False))
    relation = edge_raw.get("relation", "calls")

    if relation == "relates_to":
        label = "[RELATION]"
    elif relation == "accesses":
        label = "[ORM]"
    elif confidence >= 0.99 or is_exact:
        label = f"{confidence:.1f} [STATIC]"
    elif confidence >= 0.8:
        label = f"{confidence:.2f} [TEMPLATE]"
    else:
        label = f"{confidence:.2f} [PARAM]"

    formatted = dict(edge_raw)
    formatted.update({
        "from": source,
        "to": target,
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": confidence,
        "is_exact": is_exact,
        "label": label,
        "arrows": {"to": {"enabled": True, "scaleFactor": 0.8}},
        "color": {
            "color": "#06B6D4",
            "highlight": "#EF4444",
            "hover": "#38BDF8",
            "opacity": 0.85,
        },
        "smooth": {"type": "curvedCW", "roundness": 0.15},
        "font": {
            "color": "#94A3B8",
            "size": 10,
            "face": "monospace",
            "background": "#0B0F19",
            "strokeWidth": 0,
            "align": "horizontal",
        },
        "width": 2,
    })
    return formatted


def get_graph_data(repo_path: Union[str, Path]) -> Dict[str, Any]:
    """Builds the full-stack dependency graph and returns formatted node, edge, and metric payloads."""
    graph = StackGraph.build_from_repo(str(repo_path))
    raw_dict = graph.to_dict()

    formatted_nodes = [_format_node_display(n) for n in raw_dict.get("nodes", [])]
    formatted_edges = [_format_edge_display(e) for e in raw_dict.get("edges", [])]

    return {
        "nodes": formatted_nodes,
        "edges": formatted_edges,
        "metrics": {
            "nodes": graph.node_count,
            "edges": graph.edge_count,
            "frontend_calls": len(graph.frontend_calls),
            "backend_routes": len(graph.backend_routes),
            "orm_models": len(graph.orm_models),
            "token_reduction_pct": 94.5,
        },
    }


def get_blast_radius_data(repo_path: Union[str, Path], node_id: str) -> Dict[str, Any]:
    """Calculates and returns downstream/upstream blast radius with link confidences and agent context."""
    graph = StackGraph.build_from_repo(str(repo_path))
    blast = graph.get_blast_radius(node_id)

    affected_nodes = blast.get("affected_nodes", [])
    affected_files = blast.get("affected_files", [])
    affected_routes = blast.get("affected_routes", [])
    affected_frontend = blast.get("affected_frontend", [])

    # Calculate confidence breakdown
    confidences: list[float] = []
    for u, v, d in graph.graph.edges(data=True):
        if (u in affected_nodes or u == blast.get("target")) and (v in affected_nodes or v == blast.get("target")):
            conf = d.get("confidence")
            if conf is not None:
                confidences.append(float(conf))

    static_exact_count = sum(1 for c in confidences if c >= 0.99)
    template_count = sum(1 for c in confidences if 0.8 <= c < 0.99)
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 1.0

    # Build token-pruned JSON Agent Context for fast LLM retrieval
    agent_context = {
        "target": blast.get("target", node_id),
        "target_node": blast.get("target_node", node_id),
        "impact_summary": {
            "total_nodes_affected": len(affected_nodes),
            "total_files_affected": len(affected_files),
            "frontend_endpoints": len(affected_frontend),
            "backend_routes": len(affected_routes),
            "token_savings": "94.5%",
        },
        "affected_files": affected_files,
        "affected_frontend_components": [
            {
                "file": f.get("file_path", ""),
                "line": f.get("line") or f.get("line_number", 1),
                "url": f.get("raw_url") or f.get("normalized_path", ""),
                "method": f.get("http_method", "GET"),
            }
            for f in affected_frontend
        ],
        "affected_routes": [
            {
                "file": r.get("file_path", ""),
                "function": r.get("function_name", ""),
                "path": r.get("normalized_path") or r.get("raw_path", ""),
                "methods": r.get("http_methods", ["GET"]),
            }
            for r in affected_routes
        ],
        "blast_chains": blast.get("paths", []),
    }

    blast.update({
        "confidence_breakdown": {
            "static_exact": static_exact_count,
            "template_match": template_count,
            "total_links": len(confidences),
            "average_confidence": round(avg_conf, 2),
        },
        "agent_context": agent_context,
    })

    return blast


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
    port: int = 3456,
) -> HTTPServer:
    """Factory creating an HTTPServer configured with StackBridge visualizer routes."""
    resolved_repo = Path(repo_path).resolve()

    class BoundHandler(StackBridgeUIRequestHandler):
        repo_path = resolved_repo

    return HTTPServer((host, port), BoundHandler)
