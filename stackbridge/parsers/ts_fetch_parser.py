"""Parser for extracting fetch calls and HTTP client requests from TypeScript / TSX files."""

from typing import List
from stackbridge.core.models import FrontendEndpointCall, HttpMethod


class TypeScriptFetchParser:
    """Extracts fetch / axios / custom client calls from TypeScript/TSX AST."""

    def __init__(self) -> None:
        pass

    def parse_file(self, file_path: str) -> List[FrontendEndpointCall]:
        """Parses a TypeScript/TSX file and returns detected frontend endpoint calls."""
        # Implementation to be populated with Tree-sitter query extraction
        return []
