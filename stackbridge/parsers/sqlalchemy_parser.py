"""Parser for extracting SQLAlchemy models, fields, and relationships."""

from typing import List
from stackbridge.core.models import ORMModel


class SQLAlchemyParser:
    """Extracts SQLAlchemy ORM models, columns, and relationships from Python AST."""

    def __init__(self) -> None:
        pass

    def parse_file(self, file_path: str) -> List[ORMModel]:
        """Parses a Python file and returns detected SQLAlchemy ORM models."""
        # Implementation to be populated with Tree-sitter / AST extraction
        return []
