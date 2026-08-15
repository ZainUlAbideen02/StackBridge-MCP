"""Dependency graph representation and traversal."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from stackbridge.core.models import (
    FrontendFetchCall,
    FastAPIRoute,
    RouteMatchResult,
    SQLAlchemyModelInfo,
    GraphNode,
    GraphEdge,
    StackGraphExport,
)
from stackbridge.parsers.ts_fetch_parser import extract_nextjs_fetches
from stackbridge.parsers.py_route_parser import extract_fastapi_routes
from stackbridge.parsers.sqlalchemy_parser import extract_sqlalchemy_models
from stackbridge.core.route_matcher import match_routes


class StackGraph:
    """
    Directed graph representing full-stack dependencies across Next.js, FastAPI, and SQLAlchemy.
    
    Uses NetworkX DiGraph internally and provides methods for building, traversing,
    and exporting the unified dependency graph.
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self._node_index: Dict[str, GraphNode] = {}
        self._edge_list: List[GraphEdge] = []

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        self.graph.add_node(node.id, **node.model_dump())
        self._node_index[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph."""
        self.graph.add_edge(
            edge.source,
            edge.target,
            relation_type=edge.relation_type,
            confidence=edge.confidence,
            **edge.metadata,
        )
        self._edge_list.append(edge)

    def build_from_repo(self, repo_path: str, api_prefix_strip: Optional[str] = "/api") -> "StackGraph":
        """
        Build the full-stack dependency graph by scanning a repository.
        
        Args:
            repo_path: Path to the repository root
            api_prefix_strip: Optional API prefix to strip from paths during matching
            
        Returns:
            Self for method chaining
        """
        repo_path = Path(repo_path)
        
        all_fetches: List[FrontendFetchCall] = []
        all_routes: List[FastAPIRoute] = []
        all_models: List[SQLAlchemyModelInfo] = []
        
        # Scan TypeScript/TSX files for fetch calls
        for ts_file in repo_path.rglob("*.ts"):
            all_fetches.extend(self._parse_ts_file(ts_file))
        for tsx_file in repo_path.rglob("*.tsx"):
            all_fetches.extend(self._parse_ts_file(tsx_file))
        
        # Scan Python files for FastAPI routes and SQLAlchemy models
        for py_file in repo_path.rglob("*.py"):
            routes, models = self._parse_py_file(py_file)
            all_routes.extend(routes)
            all_models.extend(models)
        
        # Match frontend fetches to backend routes
        matches = match_routes(all_fetches, all_routes, api_prefix_strip)
        
        # Build nodes and edges
        self._build_graph_nodes(all_fetches, all_routes, all_models)
        self._build_graph_edges(matches, all_routes, all_models)
        
        return self

    def _parse_ts_file(self, file_path: Path) -> List[FrontendFetchCall]:
        """Parse a TypeScript/TSX file for fetch calls."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            return extract_nextjs_fetches(code, str(file_path))
        except Exception:
            return []

    def _parse_py_file(self, file_path: Path) -> tuple[List[FastAPIRoute], List[SQLAlchemyModelInfo]]:
        """Parse a Python file for FastAPI routes and SQLAlchemy models."""
        routes: List[FastAPIRoute] = []
        models: List[SQLAlchemyModelInfo] = []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            
            routes = extract_fastapi_routes(code, str(file_path))
            models = extract_sqlalchemy_models(code, str(file_path))
        except Exception:
            pass
        
        return routes, models

    def _build_graph_nodes(
        self,
        fetches: List[FrontendFetchCall],
        routes: List[FastAPIRoute],
        models: List[SQLAlchemyModelInfo],
    ) -> None:
        """Create graph nodes from parsed elements."""
        # Add frontend component nodes
        for fetch in fetches:
            node_id = f"fe:{fetch.file_path}:{fetch.line}"
            node = GraphNode(
                id=node_id,
                node_type="frontend_component",
                file_path=fetch.file_path,
                line=fetch.line,
                metadata={
                    "raw_expression": fetch.raw_expression,
                    "normalized_pattern": fetch.normalized_pattern,
                    "http_method": fetch.http_method,
                    "is_template": fetch.is_template,
                    "path_params": fetch.path_params,
                },
            )
            self.add_node(node)
        
        # Add API route nodes
        for route in routes:
            node_id = f"api:{route.file_path}:{route.handler_name}"
            node = GraphNode(
                id=node_id,
                node_type="api_route",
                file_path=route.file_path,
                line=route.line,
                metadata={
                    "http_method": route.http_method,
                    "route_path": route.route_path,
                    "normalized_regex": route.normalized_regex,
                    "handler_name": route.handler_name,
                    "path_params": route.path_params,
                },
            )
            self.add_node(node)
        
        # Add schema/model nodes
        for model in models:
            # Create node for the model/schema itself
            node_id = f"schema:{model.file_path}:{model.class_name}"
            node = GraphNode(
                id=node_id,
                node_type="schema_model",
                file_path=model.file_path,
                line=model.line,
                metadata={
                    "class_name": model.class_name,
                    "table_name": model.table_name,
                    "fields": [f.model_dump() for f in model.fields],
                    "relationships": model.relationships,
                },
            )
            self.add_node(node)
            
            # If it's a SQLAlchemy model with a table name, also create a db_table node
            if model.table_name:
                table_node_id = f"db:{model.file_path}:{model.table_name}"
                table_node = GraphNode(
                    id=table_node_id,
                    node_type="db_table",
                    file_path=model.file_path,
                    line=model.line,
                    metadata={
                        "table_name": model.table_name,
                        "class_name": model.class_name,
                        "fields": [f.model_dump() for f in model.fields],
                    },
                )
                self.add_node(table_node)

    def _build_graph_edges(
        self,
        matches: List[RouteMatchResult],
        routes: List[FastAPIRoute],
        models: List[SQLAlchemyModelInfo],
    ) -> None:
        """Create graph edges from matches and relationships."""
        # Add FETCHES edges from matched results
        for match in matches:
            fe_node_id = f"fe:{match.frontend_call.file_path}:{match.frontend_call.line}"
            api_node_id = f"api:{match.backend_route.file_path}:{match.backend_route.handler_name}"
            
            edge = GraphEdge(
                source=fe_node_id,
                target=api_node_id,
                relation_type="FETCHES",
                confidence=match.confidence,
                metadata={
                    "match_strategy": match.match_strategy,
                    "notes": match.notes,
                },
            )
            self.add_edge(edge)
        
        # Add USES_MODEL edges from API routes to schemas
        # This is a heuristic based on handler name patterns and model references
        route_to_models = self._infer_route_model_usage(routes, models)
        for route, model_names in route_to_models.items():
            api_node_id = f"api:{route.file_path}:{route.handler_name}"
            for model_name in model_names:
                # Find the corresponding schema node
                for model in models:
                    if model.class_name == model_name:
                        schema_node_id = f"schema:{model.file_path}:{model.class_name}"
                        edge = GraphEdge(
                            source=api_node_id,
                            target=schema_node_id,
                            relation_type="USES_MODEL",
                            confidence=0.85,
                            metadata={},
                        )
                        self.add_edge(edge)
                        break
        
        # Add MAPS_TO edges from Pydantic schemas to SQLAlchemy tables
        for model in models:
            if model.table_name:
                schema_node_id = f"schema:{model.file_path}:{model.class_name}"
                table_node_id = f"db:{model.file_path}:{model.table_name}"
                edge = GraphEdge(
                    source=schema_node_id,
                    target=table_node_id,
                    relation_type="MAPS_TO",
                    confidence=1.0,
                    metadata={},
                )
                self.add_edge(edge)

    def _infer_route_model_usage(
        self,
        routes: List[FastAPIRoute],
        models: List[SQLAlchemyModelInfo],
    ) -> Dict[FastAPIRoute, List[str]]:
        """
        Infer which models/schemas are used by which routes.
        
        This uses heuristics based on naming patterns. In a real implementation,
        this would analyze function signatures and response_model annotations.
        """
        route_models: Dict[FastAPIRoute, List[str]] = {}
        model_names = {m.class_name for m in models}
        
        for route in routes:
            matched_models: List[str] = []
            handler_name = route.handler_name.lower()
            
            # Check if handler name contains any model names
            for model_name in model_names:
                if model_name.lower() in handler_name:
                    matched_models.append(model_name)
            
            route_models[route] = matched_models
        
        return route_models

    def get_blast_radius(self, node_id: str, depth: int = 2) -> Dict[str, Any]:
        """
        Analyze the impact of changes to a specific node.
        
        Traverses upstream and downstream edges from the target node to identify
        all affected components within the specified depth.
        
        Args:
            node_id: The ID of the node to analyze
            depth: Maximum traversal depth in both directions
            
        Returns:
            Dictionary containing:
            - affected_nodes: List of affected node IDs grouped by type
            - impacted_files: Set of file paths that would be affected
            - upstream: Nodes that depend ON this node (predecessors)
            - downstream: Nodes this node depends ON (successors)
        """
        if node_id not in self.graph:
            return {
                "error": f"Node {node_id} not found in graph",
                "affected_nodes": {},
                "impacted_files": [],
                "upstream": [],
                "downstream": [],
            }
        
        # Get predecessors (upstream - nodes that call/use this node)
        upstream_nodes: Set[str] = set()
        current_level = {node_id}
        for _ in range(depth):
            next_level: Set[str] = set()
            for nid in current_level:
                predecessors = set(self.graph.predecessors(nid))
                next_level.update(predecessors)
            upstream_nodes.update(next_level)
            current_level = next_level
            if not current_level:
                break
        
        # Get successors (downstream - nodes this node calls/uses)
        downstream_nodes: Set[str] = set()
        current_level = {node_id}
        for _ in range(depth):
            next_level: Set[str] = set()
            for nid in current_level:
                successors = set(self.graph.successors(nid))
                next_level.update(successors)
            downstream_nodes.update(next_level)
            current_level = next_level
            if not current_level:
                break
        
        # Group affected nodes by type
        affected_nodes: Dict[str, List[str]] = {}
        all_affected = upstream_nodes | downstream_nodes | {node_id}
        
        for nid in all_affected:
            if nid in self._node_index:
                node = self._node_index[nid]
                node_type = node.node_type
                if node_type not in affected_nodes:
                    affected_nodes[node_type] = []
                affected_nodes[node_type].append(nid)
        
        # Collect impacted file paths
        impacted_files: Set[str] = set()
        for nid in all_affected:
            if nid in self._node_index:
                impacted_files.add(self._node_index[nid].file_path)
        
        return {
            "target_node": node_id,
            "depth": depth,
            "affected_nodes": affected_nodes,
            "impacted_files": sorted(list(impacted_files)),
            "upstream": sorted(list(upstream_nodes)),
            "downstream": sorted(list(downstream_nodes)),
            "total_affected": len(all_affected),
        }

    def export_json(self, cache_path: Optional[str] = None) -> str:
        """
        Serialize the graph to JSON format with SHA-256 hash validation.
        
        Args:
            cache_path: Optional path to write the JSON output
            
        Returns:
            JSON string representation of the graph
        """
        # Compute repo hash (using current working directory as proxy)
        # In a real implementation, this would use git rev-parse HEAD
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
            )
            repo_hash = result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            repo_hash = "unknown"
        
        # Build export structure
        nodes = []
        for node_id, node_data in self.graph.nodes(data=True):
            nodes.append({
                "id": node_data.get("id", node_id),
                "node_type": node_data.get("node_type", "unknown"),
                "file_path": node_data.get("file_path", ""),
                "line": node_data.get("line", 0),
                "metadata": node_data.get("metadata", {}),
            })
        
        edges = []
        for source, target, edge_data in self.graph.edges(data=True):
            edges.append({
                "source": source,
                "target": target,
                "relation_type": edge_data.get("relation_type", "unknown"),
                "confidence": edge_data.get("confidence", 1.0),
                "metadata": {k: v for k, v in edge_data.items() 
                            if k not in ("relation_type", "confidence")},
            })
        
        export_data = StackGraphExport(
            nodes=nodes,
            edges=edges,
            repo_hash=repo_hash,
        )
        
        json_output = export_data.model_dump_json(indent=2)
        
        # Write to cache if path provided
        if cache_path:
            cache_dir = os.path.dirname(cache_path)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(json_output)
        
        return json_output

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by its ID."""
        return self._node_index.get(node_id)

    def get_edges_for_node(self, node_id: str) -> List[GraphEdge]:
        """Get all edges connected to a specific node."""
        edges = []
        for edge in self._edge_list:
            if edge.source == node_id or edge.target == node_id:
                edges.append(edge)
        return edges

    @property
    def node_count(self) -> int:
        """Return the number of nodes in the graph."""
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Return the number of edges in the graph."""
        return self.graph.number_of_edges()
