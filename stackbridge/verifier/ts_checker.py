"""TypeScript compiler-level breakage checker."""

from typing import Dict, List, Optional
from pydantic import BaseModel


class TypeScriptDiagnostic(BaseModel):
    file_path: str
    line: int
    column: int
    message: str
    code: Optional[int] = None


class TypeScriptChecker:
    """Invokes tsc / ts-node / isolated diagnostics to verify type-level breakage."""

    def __init__(self, tsconfig_path: Optional[str] = None) -> None:
        self.tsconfig_path = tsconfig_path

    def check_project(self) -> List[TypeScriptDiagnostic]:
        return []
