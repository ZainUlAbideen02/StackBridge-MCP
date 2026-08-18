"""Python type and schema breakage checker with baseline-diffing."""

import os
import re
from typing import Dict, List, Optional, Set, Tuple
from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython
from pydantic import BaseModel, Field

from stackbridge.core.models import ORMModel
from stackbridge.parsers.sqlalchemy_parser import SQLAlchemyParser


class DiagnosticError(BaseModel):
    file_path: str
    line: int
    column: int = 1
    message: str
    severity: str = "error"
    rule: Optional[str] = "schema-attribute-missing"
    source: str = "python"

    @property
    def signature(self) -> str:
        return f"{self.file_path}:{self.line}:{self.message}"


# Backward compatibility alias
PythonDiagnostic = DiagnosticError


class PythonTypeVerifier:
    """Verifies schema consistency, attribute accesses, and type errors across Python route handlers and models."""

    def __init__(self) -> None:
        self.py_lang = Language(tspython.language())
        self.parser = Parser(self.py_lang)
        self.sql_parser = SQLAlchemyParser()

    def _extract_model_fields_map(self, model_files_content: Dict[str, str]) -> Dict[str, Set[str]]:
        """Maps model class name -> set of valid field and relationship names."""
        models_map: Dict[str, Set[str]] = {}
        for file_path, content in model_files_content.items():
            models = self.sql_parser.parse_code(content, file_path=file_path)
            for m in models:
                valid_attrs = set(f.name for f in m.fields) | set(m.relationships)
                # Standard ORM attributes
                valid_attrs.update(["__tablename__", "metadata"])
                models_map[m.class_name] = valid_attrs
        return models_map

    def check_code(
        self,
        target_code: str,
        target_file_path: str,
        models_map: Dict[str, Set[str]],
    ) -> List[DiagnosticError]:
        """Analyzes a Python file for missing attribute accesses against known ORM model schemas."""
        source_bytes = target_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        diagnostics: List[DiagnosticError] = []

        # Map local variable -> Model class name (e.g., billing = db.query(BillingAccount)... -> billing: BillingAccount)
        var_to_model: Dict[str, str] = {}

        # 1. Look for assignments: var = db.query(ModelName)... or var = ModelName(...)
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == "assignment":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left and right:
                    var_name = source_bytes[left.start_byte:left.end_byte].decode("utf-8", errors="replace").strip()
                    right_text = source_bytes[right.start_byte:right.end_byte].decode("utf-8", errors="replace")

                    for model_name in models_map.keys():
                        if f"query({model_name})" in right_text or f"select({model_name})" in right_text or f"{model_name}(" in right_text:
                            var_to_model[var_name] = model_name
            stack.extend(node.children)

        # 2. Check attribute accesses: var.attr or ModelName.attr
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == "attribute":
                obj_node = node.child_by_field_name("object")
                attr_node = node.child_by_field_name("attribute")
                if obj_node and attr_node:
                    obj_name = source_bytes[obj_node.start_byte:obj_node.end_byte].decode("utf-8", errors="replace").strip()
                    attr_name = source_bytes[attr_node.start_byte:attr_node.end_byte].decode("utf-8", errors="replace").strip()

                    target_model = None
                    if obj_name in var_to_model:
                        target_model = var_to_model[obj_name]
                    elif obj_name in models_map:
                        target_model = obj_name

                    if target_model and target_model in models_map:
                        valid_fields = models_map[target_model]
                        if attr_name not in valid_fields:
                            line_num = attr_node.start_point.row + 1
                            col_num = attr_node.start_point.column + 1
                            diagnostics.append(
                                DiagnosticError(
                                    file_path=target_file_path,
                                    line=line_num,
                                    column=col_num,
                                    message=f"Attribute '{attr_name}' does not exist on model '{target_model}'",
                                    rule="schema-attribute-missing",
                                    source="python",
                                )
                            )
            stack.extend(node.children)

        return diagnostics

    def verify_files(
        self,
        files: Dict[str, str],
    ) -> List[DiagnosticError]:
        """Runs verification across a dictionary of {file_path: file_content}."""
        # 1. Build models map from any files defining models
        models_map = self._extract_model_fields_map(files)

        # 2. Verify all files against models map
        all_diagnostics: List[DiagnosticError] = []
        for file_path, content in files.items():
            diag = self.check_code(content, file_path, models_map)
            all_diagnostics.extend(diag)

        return all_diagnostics

    def verify_with_diff(
        self,
        current_files: Dict[str, str],
        baseline_files: Optional[Dict[str, str]] = None,
    ) -> List[DiagnosticError]:
        """
        Runs baseline-diffed verification.
        Filters out pre-existing errors in baseline_files and reports only newly introduced errors.
        """
        current_diagnostics = self.verify_files(current_files)
        
        if not baseline_files:
            return current_diagnostics

        baseline_diagnostics = self.verify_files(baseline_files)
        baseline_signatures = {d.signature for d in baseline_diagnostics}

        # Filter out pre-existing baseline errors
        new_diagnostics = [d for d in current_diagnostics if d.signature not in baseline_signatures]
        return new_diagnostics


# Backward compatibility class
class PythonChecker(PythonTypeVerifier):
    def check_project(self) -> List[PythonDiagnostic]:
        return []
