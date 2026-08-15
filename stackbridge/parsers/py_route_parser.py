"""Parser for extracting FastAPI route decorators, handlers, and parameter models."""

from typing import List
from stackbridge.core.models import BackendRoute


class PythonRouteParser:
    """Extracts FastAPI route handlers and request/response models from Python AST."""

    def __init__(self) -> None:
        pass

    def parse_file(self, file_path: str) -> List[BackendRoute]:
        """Parses a Python file and returns detected FastAPI backend routes."""
        # Implementation to be populated with Tree-sitter / AST extraction
        return []
