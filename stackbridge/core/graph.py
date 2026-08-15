"""Dependency graph representation, traversal, AST repo builder, and blast-radius analysis."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import networkx as nx

from stackbridge.core.models import (
    BackendRoute,
    FrontendEndpointCall,
    GraphEdge,
    GraphNode,
    HttpMethod,
    ORMModel,
    RouteMatchResult,
    StackGraphExport,
)
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
        self._node_index: Dict[str, GraphNode] = {}
        self._edge_list: List[GraphEdge] = []

    def _normalize_path(self, path: Union[str, Path], base_dir: Optional[Union[str, Path]] = None) -> str:
        p_str = str(path).replace("\\", "/")
        if base_dir:
            b_str = str(base_dir).replace("\\", "/").rstrip("/")
            if p_str.startswith(b_str):
                p_str = p_str[len(b_str):].lstrip("/")
        return p_str

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._node_index.get(node_id)

    def add_node(self, node: GraphNode) -> None:
        self.graph.add_node(node.id, **node.model_dump())
        self._node_index[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.graph.add_edge(
            edge.source,
            edge.target,
            relation_type=edge.relation_type,
            confidence=edge.confidence,
            **edge.metadata,
        )
        self._edge_list.append(edge)

    def add_frontend_call(self, call: FrontendEndpointCall, base_dir: Optional[str] = None) -> str:
        rel_path = self._normalize_path(call.file_path, base_dir)
        node_id = f"{rel_path}::fetch::{call.line_number}"
        self.frontend_calls[node_id] = call
        self.graph.add_node(
            node_id,
            id=node_id,
            type="frontend",
            node_type="frontend_component",
            file_path=rel_path,
            line=call.line_number,
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
            id=node_id,
            type="route",
            node_type="api_route",
            file_path=rel_path,
            line=route.line_number,
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
            id=node_id,
            type="model",
            node_type="schema_model",
            file_path=rel_path,
            line=model.line_number,
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
            relation_type="FETCHES",
            confidence=confidence,
            is_exact=is_exact,
            param_mappings=param_mappings,
        )

    def link_route_to_model(self, route_node_id: str, model_node_id: str) -> None:
        self.graph.add_edge(
            route_node_id,
            model_node_id,
            relation="accesses",
            relation_type="USES_MODEL",
        )

    def link_model_to_model(self, model_node_id_1: str, model_node_id_2: str, rel_name: str = "relates_to") -> None:
        self.graph.add_edge(
            model_node_id_1,
            model_node_id_2,
            relation=rel_name,
            relation_type="RELATIONSHIP",
        )

    @classmethod
    def build_from_repo(cls, repo_path: Union[str, Path], api_prefix_strip: Optional[str] = None) -> "StackGraph":
        """Scans a repository, parses TypeScript, Python FastAPI routes, and SQLAlchemy models, and builds graph."""
        sg = cls()
        repo_dir = Path(repo_path).resolve()

        ts_parser = TypeScriptFetchParser()
        py_route_parser = PythonRouteParser()
        sql_parser = SQLAlchemyParser()

        parsed_fe_calls: List[tuple[str, FrontendEndpointCall]] = []
        parsed_routes: List[tuple[str, BackendRoute]] = []
        parsed_models: List[tuple[str, ORMModel]] = []

        py_files_data: Dict[str, Dict[str, Any]] = {}

        for root, dirs, files in os.walk(repo_dir):
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
                        with open(full_file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        source_bytes = content.encode("utf-8")
                        tree = py_route_parser.parser.parse(source_bytes)
                        prefixes = py_route_parser._extract_router_prefixes(tree.root_node, source_bytes)
                        imports, includes = py_route_parser._extract_imports_and_includes(tree.root_node, source_bytes)
                        routes = py_route_parser.parse_code(content, file_path=rel_file_path)

                        py_files_data[rel_file_path] = {
                            "routes": routes,
                            "prefixes": prefixes,
                            "imports": imports,
                            "includes": includes,
                        }
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

        # Resolve cross-file router prefixes
        file_base_prefixes: Dict[str, str] = {}
        for file_path, data in py_files_data.items():
            prefixes = data["prefixes"]
            includes = data["includes"]
            imports = data["imports"]

            # Map to imported files
            for parent_var, target_var, inc_prefix in includes:
                target_p = prefixes.get(target_var, "")
                if not target_p and inc_prefix:
                    target_p = inc_prefix
                
                if target_p:
                    imported_mod = imports.get(target_var, "")
                    if imported_mod:
                        mod_path_suffix = imported_mod.replace(".", "/")
                        for other_file in py_files_data.keys():
                            if other_file.endswith(f"{mod_path_suffix}.py") or mod_path_suffix in other_file:
                                file_base_prefixes[other_file] = target_p

        # Register routes with resolved prefixes
        for file_path, data in py_files_data.items():
            base_prefix = file_base_prefixes.get(file_path, "")
            for r in data["routes"]:
                if base_prefix and not r.raw_path.startswith(base_prefix):
                    r.raw_path = py_route_parser.resolve_subrouter_prefix(base_prefix, r.raw_path)
                    r.normalized_path = py_route_parser.resolve_subrouter_prefix(base_prefix, r.normalized_path)
                r_id = sg.add_backend_route(r)
                parsed_routes.append((r_id, r))

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

        model_name_to_id = {m.class_name: m_id for m_id, m in parsed_models}
        for r_id, route in parsed_routes:
            for model_name in route.orm_models_referenced:
                if model_name in model_name_to_id:
                    sg.link_route_to_model(r_id, model_name_to_id[model_name])

        for m_id, model in parsed_models:
            for target_rel in model.relationships:
                if target_rel in model_name_to_id:
                    sg.link_model_to_model(m_id, model_name_to_id[target_rel])

        return sg

    def _resolve_target_node(self, target_identifier: str) -> Optional[str]:
        target_clean = target_identifier.replace("\\", "/")
        if target_clean in self.graph.nodes:
            return target_clean

        for node_id, data in self.graph.nodes(data=True):
            if node_id.endswith(f"::{target_clean}") or node_id.endswith(f":{target_clean}"):
                return node_id
            if data.get("class_name") == target_clean or data.get("function_name") == target_clean:
                return node_id
            if target_clean in node_id:
                return node_id

        return None

    def get_blast_radius(self, target_identifier: str, depth: int = 5) -> Dict[str, Any]:
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

        affected_nodes: Set[str] = set()
        affected_routes: List[Dict[str, Any]] = []
        affected_frontend: List[Dict[str, Any]] = []
        affected_files: Set[str] = set()
        paths: List[List[str]] = []

        undirected = self.graph.to_undirected()
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
            "target_node": target_node,
            "found": True,
            "affected_nodes": sorted(list(affected_nodes)),
            "affected_routes": affected_routes,
            "affected_frontend": affected_frontend,
            "affected_files": sorted(list(affected_files)),
            "impacted_files": sorted(list(affected_files)),
            "paths": paths,
        }

    def to_dict(self) -> Dict[str, Any]:
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
        return json.dumps(self.to_dict(), indent=indent)

    def export_json(self, file_path: Optional[Union[str, Path]] = None) -> str:
        json_output = self.to_json()
        if file_path:
            p = Path(file_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(json_output)
        return json_output

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StackGraph":
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
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def load_json(cls, file_path: Union[str, Path]) -> "StackGraph":
        with open(file_path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())

    def save_cache(self, cache_path: Union[str, Path] = ".stackbridge_cache.json") -> None:
        self.export_json(cache_path)

    @classmethod
    def load_cache(cls, cache_path: Union[str, Path] = ".stackbridge_cache.json") -> Optional["StackGraph"]:
        if os.path.exists(cache_path):
            try:
                return cls.load_json(cache_path)
            except Exception:
                return None
        return None
