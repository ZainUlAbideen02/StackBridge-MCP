"""Parser for extracting SQLAlchemy models, fields, and relationships using Tree-sitter."""

import os
import re
from typing import Generator, List, Optional, Tuple
from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython

from stackbridge.core.models import FieldInfo, ORMField, ORMModel, SQLAlchemyModelInfo


def _walk_ast(root_node: Node) -> Generator[Node, None, None]:
    """Memory-safe, zero-allocation TreeCursor traversal across tree-sitter ASTs."""
    cursor = root_node.walk()
    visited_children = False
    while True:
        if not visited_children:
            yield cursor.node
            if cursor.goto_first_child():
                continue
        visited_children = False
        if cursor.goto_next_sibling():
            continue
        if cursor.goto_parent():
            visited_children = True
            continue
        break


class SQLAlchemyParser:
    """Extracts SQLAlchemy ORM models, columns, and relationships from Python AST."""

    _py_lang = Language(tspython.language())

    def __init__(self) -> None:
        pass

    @property
    def parser(self) -> Parser:
        return Parser(Language(tspython.language()))

    def _extract_field(self, name: str, expr_str: str) -> Optional[ORMField]:
        """Extracts ORMField details from assignment expression."""
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

    def _extract_models_from_tree(self, root_node: Node, source_bytes: bytes, file_path: str = "models.py") -> List[ORMModel]:
        """Extracts SQLAlchemy models directly from an already parsed tree-sitter AST root node."""
        models: List[ORMModel] = []

        for node in root_node.children:
            if node.type == "class_definition":
                class_chunk = source_bytes[node.start_byte:min(node.end_byte, node.start_byte + 500)].decode("utf-8", errors="replace")
                if not re.search(r"__tablename__|Column\(|mapped_column\(|\(\s*Base\s*\)|\(\s*DeclarativeBase\s*\)", class_chunk):
                    continue

                name_node = node.child_by_field_name("name")
                if not name_node:
                    continue

                class_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace").strip()
                line_number = node.start_point.row + 1
                table_name: Optional[str] = None
                fields: List[ORMField] = []
                relationships: List[str] = []

                body = node.child_by_field_name("body")
                if body:
                    for stmt in body.children:
                        target_sub = None
                        if stmt.type == "expression_statement":
                            for sub in stmt.children:
                                if sub.type in ("assignment", "annotated_assignment"):
                                    target_sub = sub
                                    break
                        elif stmt.type in ("assignment", "annotated_assignment"):
                            target_sub = stmt

                        if target_sub is not None:
                            left = target_sub.child_by_field_name("left") or target_sub.child_by_field_name("name")
                            right = target_sub.child_by_field_name("right") or target_sub.child_by_field_name("value")
                            if left is not None and right is not None:
                                try:
                                    var_name = source_bytes[left.start_byte:left.end_byte].decode("utf-8", errors="replace").strip()
                                    expr_str = source_bytes[right.start_byte:right.end_byte].decode("utf-8", errors="replace").strip()

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
                                except Exception:
                                    pass

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

    def parse_code(self, source_code: str, file_path: str = "models.py") -> List[ORMModel]:
        """Parses Python code and returns detected SQLAlchemy models."""
        source_bytes = source_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        return self._extract_models_from_tree(tree.root_node, source_bytes, file_path=file_path)

    def parse_file(self, file_path: str) -> List[ORMModel]:
        """Parses a Python file and returns detected SQLAlchemy models."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_code(content, file_path=file_path)


# Compatibility standalone function

def extract_sqlalchemy_models(code: str, file_path: str) -> List[SQLAlchemyModelInfo]:
    """Extract SQLAlchemy declarative models from code using Tree-sitter."""
    parser_obj = SQLAlchemyParser()
    orm_models = parser_obj.parse_code(code, file_path=file_path)
    result: List[SQLAlchemyModelInfo] = []
    for m in orm_models:
        field_infos = [
            FieldInfo(
                name=f.name,
                type_annotation=f.data_type,
                is_nullable=f.is_nullable,
                is_primary_key=f.is_primary_key,
            )
            for f in m.fields
        ]
        result.append(
            SQLAlchemyModelInfo(
                file_path=m.file_path,
                line=m.line_number,
                class_name=m.class_name,
                table_name=m.table_name,
                fields=field_infos,
                relationships=m.relationships,
            )
        )
    return result
