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
