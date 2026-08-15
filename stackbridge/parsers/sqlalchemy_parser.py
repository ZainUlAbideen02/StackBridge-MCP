"""Parser for extracting SQLAlchemy models, fields, and relationships using Tree-sitter."""

import os
import re
from typing import List, Optional
from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython

from stackbridge.core.models import ORMField, ORMModel


class SQLAlchemyParser:
    """Extracts SQLAlchemy ORM models, columns, and relationships from Python AST."""

    def __init__(self) -> None:
        self.py_lang = Language(tspython.language())
        self.parser = Parser(self.py_lang)

    def _extract_field(self, name: str, expr_str: str) -> Optional[ORMField]:
        """Extracts ORMField details from assignment expression."""
        # Column(String, primary_key=True, ...) or mapped_column(...)
        col_match = re.search(r"(?:Column|mapped_column)\s*\((.*?)\)", expr_str, re.DOTALL)
        if not col_match:
            return None

        inner_args = col_match.group(1).strip()
        args = [a.strip() for a in re.split(r",(?![^\(]*\))", inner_args) if a.strip()]
        if not args:
            return None

        data_type = "Unknown"
        foreign_key = None
        is_primary_key = False
        is_nullable = True

        for i, arg in enumerate(args):
            if "=" in arg:
                key, val = [x.strip() for x in arg.split("=", 1)]
                if key == "primary_key" and val.lower() == "true":
                    is_primary_key = True
                    is_nullable = False
                elif key == "nullable":
                    is_nullable = val.lower() != "false"
                elif key == "ForeignKey":
                    fk_match = re.search(r"""ForeignKey\s*\(\s*["']([^"']+)["']\s*\)""", val)
                    if fk_match:
                        foreign_key = fk_match.group(1)
            else:
                # Positional argument: data type or ForeignKey(...)
                if "ForeignKey(" in arg:
                    fk_match = re.search(r"""ForeignKey\s*\(\s*["']([^"']+)["']\s*\)""", arg)
                    if fk_match:
                        foreign_key = fk_match.group(1)
                elif data_type == "Unknown":
                    data_type = arg

        if is_primary_key:
            is_nullable = False

        return ORMField(
            name=name,
            data_type=data_type,
            is_primary_key=is_primary_key,
            is_nullable=is_nullable,
            foreign_key=foreign_key,
        )

    def _extract_relationship(self, expr_str: str) -> Optional[str]:
        """Extracts target model name from relationship(...) call."""
        rel_match = re.search(r"""relationship\s*\(\s*["']([^"']+)["']""", expr_str)
        if rel_match:
            return rel_match.group(1)
        return None

    def parse_code(self, source_code: str, file_path: str = "models.py") -> List[ORMModel]:
        """Parses Python code and returns detected SQLAlchemy models."""
        source_bytes = source_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        models: List[ORMModel] = []

        for node in tree.root_node.children:
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    continue

                class_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8")
                line_number = node.start_point.row + 1
                table_name: Optional[str] = None
                fields: List[ORMField] = []
                relationships: List[str] = []

                body = node.child_by_field_name("body")
                if body:
                    for stmt in body.children:
                        if stmt.type == "expression_statement":
                            for sub in stmt.children:
                                if sub.type == "assignment":
                                    left = sub.child_by_field_name("left")
                                    right = sub.child_by_field_name("right")
                                    if left and right:
                                        var_name = source_bytes[left.start_byte:left.end_byte].decode("utf-8").strip()
                                        expr_str = source_bytes[right.start_byte:right.end_byte].decode("utf-8").strip()

                                        if var_name == "__tablename__":
                                            table_name = expr_str.strip("'\"")
                                        elif "Column(" in expr_str or "mapped_column(" in expr_str:
                                            f = self._extract_field(var_name, expr_str)
                                            if f:
                                                fields.append(f)
                                        elif "relationship(" in expr_str:
                                            target = self._extract_relationship(expr_str)
                                            if target:
                                                relationships.append(target)

                # Only include as ORMModel if __tablename__ or fields are detected
                if table_name or fields or relationships:
                    models.append(
                        ORMModel(
                            file_path=file_path,
                            line_number=line_number,
                            class_name=class_name,
                            table_name=table_name,
                            fields=fields,
                            relationships=relationships,
                        )
                    )

        return models

    def parse_file(self, file_path: str) -> List[ORMModel]:
        """Parses a Python file and returns detected SQLAlchemy models."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_code(content, file_path=file_path)
