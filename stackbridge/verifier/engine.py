"""Unified Compiler Verifier Engine coordinating blast-radius discovery and baseline-diffing."""

import os
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
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

    _global_lock = threading.Lock()
    _dmypy_lock = threading.Lock()
    _tsserver_lock = threading.Lock()

    def __init__(
        self,
        repo_path: Optional[Union[str, Path]] = None,
        timeout_seconds: float = 6.0,
    ) -> None:
        self.repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()
        self.timeout_seconds = timeout_seconds
        self.py_verifier = PythonTypeVerifier()
        self.ts_verifier = TypeScriptTypeVerifier()
        self._lock = threading.Lock()
        self._shadow_files: Set[str] = set()
        self._daemon_pids: Dict[str, int] = {}

    def clean_shadow_files(self) -> None:
        """Removes temporary shadow files created during verification."""
        for path_str in list(self._shadow_files):
            try:
                p = Path(path_str)
                if p.exists():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        self._shadow_files.clear()

    def restart_daemon(self, daemon_type: str = "all") -> None:
        """Kills stale daemon PID processes, cleans temporary shadow files, and respawns fresh verifiers."""
        self.clean_shadow_files()

        if daemon_type in ("dmypy", "python", "all"):
            pid = self._daemon_pids.pop("dmypy", None)
            if pid:
                try:
                    os.kill(pid, 9)
                except Exception:
                    pass
            self.py_verifier = PythonTypeVerifier()

        if daemon_type in ("tsserver", "typescript", "all"):
            pid = self._daemon_pids.pop("tsserver", None)
            if pid:
                try:
                    os.kill(pid, 9)
                except Exception:
                    pass
            self.ts_verifier = TypeScriptTypeVerifier()

    def reset_verifiers(self) -> None:
        """Clean restart of verifier worker state on crash or timeout."""
        self.restart_daemon("all")

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
        4. Runs baseline-diffed verification safely under concurrency locks and timeouts.
        """
        with self._lock:
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
                normalized_mod = Path(mod_file).as_posix().strip("/")
                current_files[normalized_mod] = mod_content
                if normalized_mod not in baseline_files:
                    disk_content = self._read_file_safe(active_repo / normalized_mod)
                    if disk_content is not None:
                        baseline_files[normalized_mod] = disk_content
                    else:
                        baseline_files[normalized_mod] = ""

            new_diagnostics: List[DiagnosticError] = []

            # 4. Run Python baseline-diffed verification with dmypy concurrency lock & timeout
            py_baseline = {k: v for k, v in baseline_files.items() if k.endswith(".py")}
            py_current = {k: v for k, v in current_files.items() if k.endswith(".py")}

            if py_current:
                with self._dmypy_lock:
                    def _run_py():
                        return self.py_verifier.verify_with_diff(
                            current_files=py_current,
                            baseline_files=py_baseline,
                        )

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        try:
                            fut = executor.submit(_run_py)
                            py_diags = fut.result(timeout=self.timeout_seconds)
                            new_diagnostics.extend(py_diags)
                        except Exception as e:
                            self.restart_daemon("dmypy")
                            target_file = list(py_current.keys())[0] if py_current else "backend"
                            reason = f"timeout ({self.timeout_seconds}s)" if isinstance(e, FuturesTimeoutError) else f"crash/error: {str(e)}"
                            new_diagnostics.append(
                                DiagnosticError(
                                    file_path=target_file,
                                    line=1,
                                    column=1,
                                    message=f"DAEMON_RECOVERED: dmypy daemon recovered after {reason}",
                                    rule="DAEMON_RECOVERED",
                                    severity="error",
                                    source="dmypy",
                                )
                            )

            # 5. Run TypeScript baseline-diffed verification with tsserver concurrency lock & timeout
            ts_baseline = {k: v for k, v in baseline_files.items() if k.endswith((".ts", ".tsx", ".js", ".jsx"))}
            ts_current = {k: v for k, v in current_files.items() if k.endswith((".ts", ".tsx", ".js", ".jsx"))}

            if ts_current:
                with self._tsserver_lock:
                    def _run_ts():
                        return self.ts_verifier.verify_with_diff(
                            current_files=ts_current,
                            baseline_files=ts_baseline,
                        )

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        try:
                            fut = executor.submit(_run_ts)
                            ts_new_diags = fut.result(timeout=self.timeout_seconds)
                            new_diagnostics.extend(ts_new_diags)
                        except Exception as e:
                            self.restart_daemon("tsserver")
                            target_file = list(ts_current.keys())[0] if ts_current else "frontend"
                            reason = f"timeout ({self.timeout_seconds}s)" if isinstance(e, FuturesTimeoutError) else f"crash/error: {str(e)}"
                            new_diagnostics.append(
                                DiagnosticError(
                                    file_path=target_file,
                                    line=1,
                                    column=1,
                                    message=f"DAEMON_RECOVERED: tsserver daemon recovered after {reason}",
                                    rule="DAEMON_RECOVERED",
                                    severity="error",
                                    source="tsserver",
                                )
                            )

            has_breakage = len(new_diagnostics) > 0

            return VerificationReport(
                has_breakage=has_breakage,
                diagnostics=new_diagnostics,
                impacted_files=impacted_files_list,
                verified_files=sorted(list(current_files.keys())),
                error_count=len(new_diagnostics),
            )
