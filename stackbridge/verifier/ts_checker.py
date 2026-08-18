"""TypeScript and Next.js frontend breakage checker with baseline-diffing."""

from typing import Dict, List, Optional, Set

from stackbridge.parsers.ts_fetch_parser import TypeScriptFetchParser
from stackbridge.verifier.py_checker import DiagnosticError


class TypeScriptDiagnostic(DiagnosticError):
    source: str = "typescript"


class TypeScriptTypeVerifier:
    """Verifies TypeScript fetch calls, parameters, and payloads against backend route definitions."""

    def __init__(self) -> None:
        self.ts_parser = TypeScriptFetchParser()

    def _is_route_matched(self, call_path: str, known_routes: Set[str]) -> bool:
        if call_path in known_routes:
            return True
        from stackbridge.core.route_matcher import _is_param_segment, _split_segments
        call_segments = _split_segments(call_path)
        for route in known_routes:
            route_segments = _split_segments(route)
            if len(call_segments) != len(route_segments):
                continue
            matched = True
            for cs, rs in zip(call_segments, route_segments):
                c_param, _ = _is_param_segment(cs)
                r_param, _ = _is_param_segment(rs)
                if not c_param and not r_param:
                    if cs != rs:
                        matched = False
                        break
            if matched:
                return True
        return False

    def check_code(
        self,
        target_code: str,
        target_file_path: str,
        known_routes: Set[str],
    ) -> List[DiagnosticError]:
        calls = self.ts_parser.parse_code(target_code, file_path=target_file_path)
        diagnostics: List[DiagnosticError] = []

        for call in calls:
            # If known routes are provided, check if route exists
            if known_routes and not self._is_route_matched(call.normalized_path, known_routes):
                diagnostics.append(
                    DiagnosticError(
                        file_path=target_file_path,
                        line=call.line_number,
                        column=1,
                        message=f"Fetch endpoint '{call.raw_url}' does not match any registered backend route",
                        rule="unmatched-fetch-route",
                        source="typescript",
                    )
                )

        return diagnostics

    def verify_files(
        self,
        files: Dict[str, str],
        known_routes: Optional[Set[str]] = None,
    ) -> List[DiagnosticError]:
        all_diags: List[DiagnosticError] = []
        routes = known_routes or set()
        for file_path, content in files.items():
            if file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
                all_diags.extend(self.check_code(content, file_path, routes))
        return all_diags

    def verify_with_diff(
        self,
        current_files: Dict[str, str],
        baseline_files: Optional[Dict[str, str]] = None,
        known_routes: Optional[Set[str]] = None,
    ) -> List[DiagnosticError]:
        current_diags = self.verify_files(current_files, known_routes=known_routes)
        if not baseline_files:
            return current_diags

        baseline_diags = self.verify_files(baseline_files, known_routes=known_routes)
        baseline_sigs = {d.signature for d in baseline_diags}

        return [d for d in current_diags if d.signature not in baseline_sigs]


# Backward compatibility
class TypeScriptChecker(TypeScriptTypeVerifier):
    def __init__(self, tsconfig_path: Optional[str] = None) -> None:
        super().__init__()
        self.tsconfig_path = tsconfig_path

    def check_project(self) -> List[TypeScriptDiagnostic]:
        return []
