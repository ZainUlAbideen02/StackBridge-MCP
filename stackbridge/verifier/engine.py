"""Unified Compiler Verifier Engine coordinating blast-radius discovery and baseline-diffing."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field

from stackbridge.core.graph import StackGraph
from stackbridge.verifier.py_checker import DiagnosticError, PythonTypeVerifier
from stackbridge.verifier.ts_checker import TypeScriptTypeVerifier


class VerificationReport(BaseModel):
    has_breakage: bool
    diagnostics: List[DiagnosticError] = Field(default_factory=list)
    impacted_files: List[str] = Field(default_factory=list)
    verified_files: List[str] = Field(default_factory=list)
    error_count: int = 0


class VerifierEngine:
    """Coordinates blast-radius dependency analysis and targeted baseline-diffed verification."""

    def __init__(self, repo_path: Optional[Union[str, Path]] = None) -> None:
        self.repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()
        self.py_verifier = PythonTypeVerifier()
        self.ts_verifier = TypeScriptTypeVerifier()

    def _read_file_safe(self, file_path: Union[str, Path]) -> Optional[str]:
        p = Path(file_path)
        if not p.is_absolute():
            p = self.repo_path / p
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return None
        return None

    def verify_impacted_files(
        self,
        modified_files: Dict[str, str],
        repo_path: Optional[Union[str, Path]] = None,
        graph: Optional[StackGraph] = None,
    ) -> VerificationReport:
        """
        1. Identifies blast radius of all modified_files using StackGraph.
        2. Gathers baseline versions of all impacted files.
        3. Applies modified_files in-memory overlay.
        4. Runs baseline-diffed verification to isolate new breaking changes.
        """
        active_repo = Path(repo_path).resolve() if repo_path else self.repo_path
        
        # 1. Build or use existing graph
        active_graph = graph or StackGraph.build_from_repo(str(active_repo))

        # 2. Compute full blast radius across modified files
        all_impacted_files: Set[str] = set()
        for mod_file in modified_files.keys():
            all_impacted_files.add(mod_file)
            blast = active_graph.get_blast_radius(mod_file)
            if blast.get("found"):
                for aff in blast.get("affected_files", []):
                    all_impacted_files.add(aff)

        # Normalize relative file paths
        impacted_files_list = sorted(list(all_impacted_files))

        # 3. Read baseline files
        baseline_files: Dict[str, str] = {}
        current_files: Dict[str, str] = {}

        for rel_file in impacted_files_list:
            disk_content = self._read_file_safe(active_repo / rel_file)
            if disk_content is not None:
                baseline_files[rel_file] = disk_content
                current_files[rel_file] = disk_content

        # Apply in-memory modifications
        for mod_file, mod_content in modified_files.items():
            # Match either exact key or relative key
            normalized_mod = mod_file.replace("\\", "/")
            current_files[normalized_mod] = mod_content
            if normalized_mod not in baseline_files:
                # Try finding in disk
                disk_content = self._read_file_safe(active_repo / normalized_mod)
                if disk_content is not None:
                    baseline_files[normalized_mod] = disk_content
                else:
                    baseline_files[normalized_mod] = ""

        # 4. Run Python baseline-diffed verification
        py_baseline = {k: v for k, v in baseline_files.items() if k.endswith(".py")}
        py_current = {k: v for k, v in current_files.items() if k.endswith(".py")}
        
        new_diagnostics = self.py_verifier.verify_with_diff(
            current_files=py_current,
            baseline_files=py_baseline,
        )

        # 5. Run TypeScript baseline-diffed verification if applicable
        ts_baseline = {k: v for k, v in baseline_files.items() if k.endswith((".ts", ".tsx", ".js", ".jsx"))}
        ts_current = {k: v for k, v in current_files.items() if k.endswith((".ts", ".tsx", ".js", ".jsx"))}
        
        if ts_current:
            ts_new_diags = self.ts_verifier.verify_with_diff(
                current_files=ts_current,
                baseline_files=ts_baseline,
            )
            new_diagnostics.extend(ts_new_diags)

        has_breakage = len(new_diagnostics) > 0

        return VerificationReport(
            has_breakage=has_breakage,
            diagnostics=new_diagnostics,
            impacted_files=impacted_files_list,
            verified_files=sorted(list(current_files.keys())),
            error_count=len(new_diagnostics),
        )
