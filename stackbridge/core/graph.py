"""Dependency graph representation, traversal, AST repo builder, and blast-radius analysis."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import networkx as nx

from stackbridge.core.models import BackendRoute, FrontendEndpointCall, HttpMethod, ORMModel, RouteMatchResult
from stackbridge.core.route_matcher import match_frontend_call_to_routes
from stackbridge.parsers.py_route_parser import PythonRouteParser
from stackbridge.parsers.sqlalchemy_parser import SQLAlchemyParser
from stackbridge.parsers.ts_fetch_parser import TypeScriptFetchParser


class StackGraph:
    """Unified full-stack dependency graph across Next.js, FastAPI, and SQLAlchemy."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.frontend_calls: Dict[str, FrontendEndpointCall] = {}
        self.backend_routes: Dict[str, BackendRoute] = {}
        self.orm_models: Dict[str, ORMModel] = {}

    def _normalize_path(self, path: Union[str, Path], base_dir: Optional[Union[str, Path]] = None) -> str:
        p_str = str(path).replace("\\", "/")
        if base_dir:
            b_str = str(base_dir).replace("\\", "/").rstrip("/")
            if p_str.startswith(b_str):
                p_str = p_str[len(b_str):].lstrip("/")
        return p_str

    def add_frontend_call(self, call: FrontendEndpointCall, base_dir: Optional[str] = None) -> str:
        rel_path = self._normalize_path(call.file_path, base_dir)
        node_id = f"{rel_path}::fetch::{call.line_number}"
        self.frontend_calls[node_id] = call
        self.graph.add_node(
            node_id,
            type="frontend",
            file_path=rel_path,
            line_number=call.line_number,
            raw_url=call.raw_url,
            normalized_path=call.normalized_path,
            http_method=call.http_method.value if isinstance(call.http_method, HttpMethod) else call.http_method,
            is_template=call.is_template,
            data=call.model_dump(),
        )
        return node_id

    def add_backend_route(self, route: BackendRoute, base_dir: Optional[str] = None) -> str:
        rel_path = self._normalize_path(route.file_path, base_dir)
        node_id = f"{rel_path}::{route.function_name}"
        self.backend_routes[node_id] = route
        self.graph.add_node(
            node_id,
            type="route",
            file_path=rel_path,
            line_number=route.line_number,
            function_name=route.function_name,
            raw_path=route.raw_path,
            normalized_path=route.normalized_path,
            http_methods=[m.value if isinstance(m, HttpMethod) else m for m in route.http_methods],
            response_model=route.response_model,
            data=route.model_dump(),
        )
        return node_id

    def add_orm_model(self, model: ORMModel, base_dir: Optional[str] = None) -> str:
        rel_path = self._normalize_path(model.file_path, base_dir)
        node_id = f"{rel_path}::{model.class_name}"
        self.orm_models[node_id] = model
        self.graph.add_node(
            node_id,
            type="model",
            file_path=rel_path,
            line_number=model.line_number,
            class_name=model.class_name,
            table_name=model.table_name,
            fields=[f.model_dump() for f in model.fields],
            relationships=model.relationships,
            data=model.model_dump(),
        )
        return node_id

    def link_frontend_to_route(
        self, fe_node_id: str, route_node_id: str, confidence: float, is_exact: bool, param_mappings: Dict[str, str]
    ) -> None:
        self.graph.add_edge(
            fe_node_id,
            route_node_id,
            relation="calls",
            confidence=confidence,
            is_exact=is_exact,
            param_mappings=param_mappings,
        )

    def link_route_to_model(self, route_node_id: str, model_node_id: str) -> None:
        self.graph.add_edge(
            route_node_id,
            model_node_id,
            relation="accesses",
        )

    def link_model_to_model(self, model_node_id_1: str, model_node_id_2: str, rel_name: str = "relates_to") -> None:
        self.graph.add_edge(
            model_node_id_1,
            model_node_id_2,
            relation=rel_name,
        )

    @classmethod
    def build_from_repo(cls, repo_path: Union[str, Path]) -> "StackGraph":
        """Scans a repository, parses TypeScript, Python FastAPI routes, and SQLAlchemy models, and builds graph."""
        sg = cls()
        repo_dir = Path(repo_path).resolve()

        ts_parser = TypeScriptFetchParser()
        py_route_parser = PythonRouteParser()
        sql_parser = SQLAlchemyParser()

        parsed_fe_calls: List[tuple[str, FrontendEndpointCall]] = []
        parsed_routes: List[tuple[str, BackendRoute]] = []
        parsed_models: List[tuple[str, ORMModel]] = []

        # Walk repository files
        for root, dirs, files in os.walk(repo_dir):
            # Ignore .git, node_modules, .venv, etc.
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "__pycache__", ".pytest_cache")]
            for file in files:
                full_file_path = os.path.join(root, file)
                rel_file_path = os.path.relpath(full_file_path, repo_dir).replace("\\", "/")
                ext = os.path.splitext(file)[1].lower()

                if ext in (".ts", ".tsx", ".js", ".jsx"):
                    try:
                        calls = ts_parser.parse_file(full_file_path)
                        for c in calls:
                            c.file_path = rel_file_path
                            fe_id = sg.add_frontend_call(c)
                            parsed_fe_calls.append((fe_id, c))
                    except Exception:
                        pass

                elif ext == ".py":
                    try:
                        routes = py_route_parser.parse_file(full_file_path)
                        for r in routes:
                            r.file_path = rel_file_path
                            r_id = sg.add_backend_route(r)
                            parsed_routes.append((r_id, r))
                    except Exception:
                        pass

                    try:
                        models = sql_parser.parse_file(full_file_path)
                        for m in models:
                            m.file_path = rel_file_path
                            m_id = sg.add_orm_model(m)
                            parsed_models.append((m_id, m))
                    except Exception:
                        pass

        # 1. Match frontend calls to backend routes
        all_backend_routes = [r for _, r in parsed_routes]
        route_to_id = {r.raw_path: r_id for r_id, r in parsed_routes}
        route_to_id.update({r.normalized_path: r_id for r_id, r in parsed_routes})
        route_func_to_id = {f"{r.file_path}::{r.function_name}": r_id for r_id, r in parsed_routes}

        for fe_id, fe_call in parsed_fe_calls:
            matches = match_frontend_call_to_routes(fe_call, all_backend_routes, min_confidence=0.5)
            for match in matches:
                target_route = match.backend_route
                r_id = route_func_to_id.get(f"{target_route.file_path}::{target_route.function_name}")
                if not r_id:
                    r_id = route_to_id.get(target_route.normalized_path)
                if r_id:
                    sg.link_frontend_to_route(
                        fe_node_id=fe_id,
                        route_node_id=r_id,
                        confidence=match.confidence,
                        is_exact=match.is_exact,
                        param_mappings=match.param_mappings,
                    )

        # 2. Link routes to ORM models referenced
        model_name_to_id = {m.class_name: m_id for m_id, m in parsed_models}
        for r_id, route in parsed_routes:
            for model_name in route.orm_models_referenced:
                if model_name in model_name_to_id:
                    sg.link_route_to_model(r_id, model_name_to_id[model_name])

        # 3. Link ORM relationships
        for m_id, model in parsed_models:
            for target_rel in model.relationships:
                if target_rel in model_name_to_id:
                    sg.link_model_to_model(m_id, model_name_to_id[target_rel])

        return sg

    def _resolve_target_node(self, target_identifier: str) -> Optional[str]:
        """Finds node ID matching identifier (exact id, symbol name, or path suffix)."""
        target_clean = target_identifier.replace("\\", "/")
        if target_clean in self.graph.nodes:
            return target_clean

        # Check if symbol matches class name or function name
        for node_id, data in self.graph.nodes(data=True):
            if node_id.endswith(f"::{target_clean}") or node_id.endswith(f":{target_clean}"):
                return node_id
            if data.get("class_name") == target_clean or data.get("function_name") == target_clean:
                return node_id
            if target_clean in node_id:
                return node_id

        return None

    def get_blast_radius(self, target_identifier: str) -> Dict[str, Any]:
        """
        Traces full-stack blast radius of a change at target_identifier (e.g. 'backend/models.py::BillingAccount').
        Traces upstream routes and frontend callers.
        """
        target_node = self._resolve_target_node(target_identifier)
        if not target_node:
            return {
                "target": target_identifier,
                "found": False,
                "affected_nodes": [],
                "affected_routes": [],
                "affected_frontend": [],
                "affected_files": [],
                "paths": [],
            }

        # Build undirected view or traverse reverse edges for upstream dependencies
        affected_nodes: Set[str] = set()
        affected_routes: List[Dict[str, Any]] = []
        affected_frontend: List[Dict[str, Any]] = []
        affected_files: Set[str] = set()
        paths: List[List[str]] = []

        # Undirected graph for full blast radius
        undirected = self.graph.to_undirected()
        
        # Traverse BFS from target
        visited = set([target_node])
        queue = [[target_node]]

        while queue:
            current_path = queue.pop(0)
            curr = current_path[-1]

            for neighbor in undirected.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = list(current_path) + [neighbor]
                    paths.append(new_path)
                    queue.append(new_path)

        for node_id in visited:
            if node_id == target_node:
                continue
            affected_nodes.add(node_id)
            node_data = self.graph.nodes[node_id]
            node_type = node_data.get("type")
            file_path = node_data.get("file_path", "")
            if file_path:
                affected_files.add(file_path)

            if node_type == "route":
                affected_routes.append({"node_id": node_id, **node_data})
            elif node_type == "frontend":
                affected_frontend.append({"node_id": node_id, **node_data})

        return {
            "target": target_node,
            "found": True,
            "affected_nodes": sorted(list(affected_nodes)),
            "affected_routes": affected_routes,
            "affected_frontend": affected_frontend,
            "affected_files": sorted(list(affected_files)),
            "paths": paths,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serializes graph and metadata to dictionary."""
        nodes_data = []
        for n, d in self.graph.nodes(data=True):
            clean_d = {k: v for k, v in d.items() if k != "data"}
            nodes_data.append({"id": n, **clean_d})

        edges_data = []
        for u, v, d in self.graph.edges(data=True):
            edges_data.append({"source": u, "target": v, **d})

        return {
            "version": "1.0.0",
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
            "nodes": nodes_data,
            "edges": edges_data,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes graph to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def export_json(self, file_path: Union[str, Path]) -> None:
        """Exports graph JSON to file."""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StackGraph":
        """Deserializes graph from dictionary."""
        sg = cls()
        for n in data.get("nodes", []):
            node_id = n["id"]
            node_props = {k: v for k, v in n.items() if k != "id"}
            sg.graph.add_node(node_id, **node_props)

        for e in data.get("edges", []):
            src = e["source"]
            tgt = e["target"]
            edge_props = {k: v for k, v in e.items() if k not in ("source", "target")}
            sg.graph.add_edge(src, tgt, **edge_props)

        return sg

    @classmethod
    def from_json(cls, json_str: str) -> "StackGraph":
        """Deserializes graph from JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def load_json(cls, file_path: Union[str, Path]) -> "StackGraph":
        """Loads graph from JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())

    def save_cache(self, cache_path: Union[str, Path] = ".stackbridge_cache.json") -> None:
        """Saves current graph to cache file."""
        self.export_json(cache_path)

    @classmethod
    def load_cache(cls, cache_path: Union[str, Path] = ".stackbridge_cache.json") -> Optional["StackGraph"]:
        """Loads graph from cache file if it exists."""
        if os.path.exists(cache_path):
            try:
                return cls.load_json(cache_path)
            except Exception:
                return None
        return None
