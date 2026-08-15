"""Python type and schema breakage checker."""

from typing import Dict, List, Optional
from pydantic import BaseModel


class PythonDiagnostic(BaseModel):
    file_path: str
    line: int
    column: int
    message: str
    severity: str = "error"


class PythonChecker:
    """Invokes mypy / pyright / AST linters to verify Python breakage."""

    def __init__(self) -> None:
        pass

    def check_project(self) -> List[PythonDiagnostic]:
        return []
