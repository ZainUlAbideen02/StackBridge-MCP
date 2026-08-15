"""Dependency graph representation and traversal."""

from typing import Dict, List, Optional
import networkx as nx
from stackbridge.core.models import FrontendEndpointCall, BackendRoute, ORMModel


class FullStackGraph:
    """Directed graph representing full-stack dependencies across Next.js, FastAPI, and SQLAlchemy."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def add_frontend_call(self, call: FrontendEndpointCall) -> str:
        node_id = f"fe:{call.file_path}:{call.line_number}"
        self.graph.add_node(node_id, type="frontend_call", data=call)
        return node_id

    def add_backend_route(self, route: BackendRoute) -> str:
        node_id = f"be:{route.file_path}:{route.function_name}"
        self.graph.add_node(node_id, type="backend_route", data=route)
        return node_id

    def add_orm_model(self, model: ORMModel) -> str:
        node_id = f"orm:{model.file_path}:{model.class_name}"
        self.graph.add_node(node_id, type="orm_model", data=model)
        return node_id

    def link_frontend_to_backend(self, fe_node_id: str, be_node_id: str, metadata: Optional[Dict] = None) -> None:
        self.graph.add_edge(fe_node_id, be_node_id, relation="calls", **(metadata or {}))

    def link_backend_to_orm(self, be_node_id: str, orm_node_id: str, metadata: Optional[Dict] = None) -> None:
        self.graph.add_edge(be_node_id, orm_node_id, relation="accesses", **(metadata or {}))
