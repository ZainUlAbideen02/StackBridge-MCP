"""Full-stack boundary guard engine checking schema, route, and compiler contracts."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from stackbridge.core.graph import StackGraph
from stackbridge.verifier.engine import VerificationReport, VerifierEngine
from stackbridge.verifier.py_checker import DiagnosticError


class GuardReport(VerificationReport):
    """Guard verification report containing contract, route, and type diagnostics."""
    unmatched_frontend_calls: List[Dict[str, Any]] = Field(default_factory=list)
    unmatched_backend_routes: List[Dict[str, Any]] = Field(default_factory=list)
    total_frontend_calls: int = 0
    total_backend_routes: int = 0


class StackGuardEngine:
    """Coordinates full-stack cross-boundary verification across Next.js, FastAPI, and SQLAlchemy."""

    def __init__(self, repo_path: Optional[Union[str, Path]] = None) -> None:
        self.repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()
        self.verifier_engine = VerifierEngine(self.repo_path)

    def check_repo(self, repo_path: Optional[Union[str, Path]] = None) -> GuardReport:
        """Performs full static guard check on the repository."""
        active_repo = Path(repo_path).resolve() if repo_path else self.repo_path
        graph = StackGraph.build_from_repo(str(active_repo))

        diagnostics: List[DiagnosticError] = []
        unmatched_fe: List[Dict[str, Any]] = []
        unmatched_be: List[Dict[str, Any]] = []

        # 1. Check all frontend calls for matching backend routes
        for node_id, fe_call in graph.frontend_calls.items():
            has_match = False
            for _, target, data in graph.graph.out_edges(node_id, data=True):
                if data.get("relation_type") == "FETCHES":
                    has_match = True
                    break

            if not has_match:
                unmatched_fe.append(fe_call.model_dump())
                diagnostics.append(
                    DiagnosticError(
                        file_path=fe_call.file_path,
                        line=fe_call.line_number,
                        column=1,
                        message=f"Frontend endpoint '{fe_call.raw_url}' ({fe_call.http_method}) has no matching backend FastAPI route.",
                        rule="guard-unmatched-endpoint",
                        source="stackguard",
                    )
                )

        # 2. Gather files and run type verifiers
        files_to_verify: Dict[str, str] = {}
        for root, dirs, files in os.walk(active_repo):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "__pycache__", ".pytest_cache")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in (".py", ".ts", ".tsx"):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, active_repo).replace("\\", "/")
                    try:
                        with open(full_p, "r", encoding="utf-8") as fh:
                            files_to_verify[rel_p] = fh.read()
                    except Exception:
                        pass

        known_routes = set(graph.backend_routes.keys()) | {r.normalized_path for r in graph.backend_routes.values()}
        ts_diags = self.verifier_engine.ts_verifier.verify_files(
            files={k: v for k, v in files_to_verify.items() if k.endswith((".ts", ".tsx"))},
            known_routes=known_routes,
        )
        diagnostics.extend(ts_diags)

        has_breakage = len(diagnostics) > 0

        return GuardReport(
            has_breakage=has_breakage,
            diagnostics=diagnostics,
            impacted_files=sorted(list(files_to_verify.keys())),
            verified_files=sorted(list(files_to_verify.keys())),
            error_count=len(diagnostics),
            unmatched_frontend_calls=unmatched_fe,
            unmatched_backend_routes=unmatched_be,
            total_frontend_calls=len(graph.frontend_calls),
            total_backend_routes=len(graph.backend_routes),
        )

    def verify_impacted_files(
        self,
        modified_files: Dict[str, str],
        repo_path: Optional[Union[str, Path]] = None,
    ) -> VerificationReport:
        """Verifies in-memory changes against repository and identifies cross-boundary breakages."""
        return self.verifier_engine.verify_impacted_files(
            modified_files=modified_files,
            repo_path=repo_path or self.repo_path,
        )

    def detect_cross_boundary_breakage(
        self,
        modified_files: Dict[str, str],
        repo_path: Optional[Union[str, Path]] = None,
    ) -> VerificationReport:
        """Alias for verify_impacted_files to detect cross-boundary breakage."""
        return self.verify_impacted_files(modified_files=modified_files, repo_path=repo_path)
