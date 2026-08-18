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
)


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
        p_str = Path(path).as_posix() if isinstance(path, (str, Path)) else str(path).replace("\\", "/")
        if base_dir:
            b_str = Path(base_dir).as_posix().rstrip("/")
            if p_str.startswith(b_str):
                p_str = p_str[len(b_str):].lstrip("/")
        return p_str.replace("\\", "/")

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
    def build_from_repo(cls, repo_path: Union[str, Path], api_prefix_strip: Optional[str] = None, use_cache: bool = True) -> "StackGraph":
        """Scans a repository, parses TypeScript, Python FastAPI routes, and SQLAlchemy models, and builds graph."""
        from stackbridge.core.indexer import IncrementalIndexer

        indexer = IncrementalIndexer(repo_path=repo_path)
        graph, _ = indexer.index(use_cache=use_cache)
        return graph

    def _resolve_target_node(self, target_identifier: str) -> Optional[str]:
        target_clean = target_identifier.replace("\\", "/")
        if target_clean in self.graph.nodes:
            return target_clean

        for node_id, data in self.graph.nodes(data=True):
            node_clean = node_id.replace("\\", "/")
            if node_clean == target_clean or node_clean.endswith(f"::{target_clean}") or node_clean.endswith(f":{target_clean}"):
                return node_id
            if target_clean.endswith(node_clean):
                return node_id
            if "::" in target_clean:
                symbol = target_clean.split("::")[-1]
                path_part = target_clean.split("::")[0]
                if data.get("function_name") == symbol or data.get("class_name") == symbol:
                    if not path_part or path_part in node_clean or node_clean.endswith(path_part):
                        return node_id
            if data.get("class_name") == target_clean or data.get("function_name") == target_clean:
                return node_id
            if target_clean in node_clean or node_clean in target_clean:
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
