"""Data models for StackBridge components and AST extraction."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"
    MCP_TOOL = "MCP_TOOL"
    MCP_RESOURCE = "MCP_RESOURCE"


class EndpointParam(BaseModel):
    name: str
    param_type: str = "path"  # "path", "query", "header", "body"
    required: bool = True
    schema_type: Optional[str] = None


class FrontendEndpointCall(BaseModel):
    file_path: str
    line_number: int
    raw_url: str
    normalized_path: str
    http_method: HttpMethod = HttpMethod.GET
    path_params: List[str] = Field(default_factory=list)
    query_params: List[str] = Field(default_factory=list)
    is_template: bool = False
    body_type: Optional[str] = None


class BackendRoute(BaseModel):
    file_path: str
    line_number: int
    function_name: str
    raw_path: str
    normalized_path: str
    http_methods: List[HttpMethod] = Field(default_factory=lambda: [HttpMethod.GET])
    path_params: List[EndpointParam] = Field(default_factory=list)
    query_params: List[EndpointParam] = Field(default_factory=list)
    request_model: Optional[str] = None
    response_model: Optional[str] = None
    orm_models_referenced: List[str] = Field(default_factory=list)


class ORMField(BaseModel):
    name: str
    data_type: str
    is_primary_key: bool = False
    is_nullable: bool = True
    foreign_key: Optional[str] = None


class ORMModel(BaseModel):
    file_path: str
    line_number: int
    class_name: str
    table_name: Optional[str] = None
    fields: List[ORMField] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)


# Alternative/Complementary schema representations

class FrontendFetchCall(BaseModel):
    """Represents a fetch() call extracted from TypeScript/TSX code."""
    file_path: str
    line: int
    raw_expression: str
    normalized_pattern: str
    http_method: str = "GET"
    is_template: bool
    path_params: List[str] = Field(default_factory=list)


class FastAPIRoute(BaseModel):
    """Represents a FastAPI route decorator extracted from Python code."""
    file_path: str
    line: int
    http_method: str
    route_path: str
    normalized_regex: str
    handler_name: str
    path_params: List[str] = Field(default_factory=list)


class RouteMatchResult(BaseModel):
    """Represents a match result between a frontend fetch call and a backend route."""
    frontend_call: Any
    backend_route: Any
    confidence: float
    is_exact: bool = False
    param_mappings: Dict[str, str] = Field(default_factory=dict)
    match_strategy: Optional[str] = None
    notes: Optional[str] = None


class FieldInfo(BaseModel):
    """Represents a field/column in a SQLAlchemy model or Pydantic schema."""
    name: str
    type_annotation: str
    is_nullable: bool = False
    is_primary_key: bool = False


class SQLAlchemyModelInfo(BaseModel):
    """Represents a SQLAlchemy declarative model or Pydantic schema extracted from Python code."""
    file_path: str
    line: int
    class_name: str
    table_name: Optional[str] = None
    fields: List[FieldInfo] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Represents a node in the full-stack dependency graph."""
    id: str
    node_type: str  # "frontend_component", "api_route", "schema_model", "db_table"
    file_path: str
    line: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Represents an edge in the full-stack dependency graph."""
    source: str
    target: str
    relation_type: str  # "FETCHES", "USES_SCHEMA", "MAPS_TO", "HANDLED_BY", "USES_MODEL"
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StackGraphExport(BaseModel):
    """Represents the serialized export of the full-stack dependency graph."""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    repo_hash: str
