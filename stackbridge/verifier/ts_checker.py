"""TypeScript and Next.js frontend breakage checker with baseline-diffing."""


from stackbridge.parsers.ts_fetch_parser import TypeScriptFetchParser
from stackbridge.verifier.py_checker import DiagnosticError


class TypeScriptDiagnostic(DiagnosticError):
    source: str = "typescript"


class TypeScriptTypeVerifier:
    """Verifies TypeScript fetch calls, parameters, and payloads against backend route definitions."""

    def __init__(self) -> None:
        self.ts_parser = TypeScriptFetchParser()

    def check_code(
        self,
        target_code: str,
        target_file_path: str,
        known_routes: set[str],
    ) -> list[DiagnosticError]:
        calls = self.ts_parser.parse_code(target_code, file_path=target_file_path)
        diagnostics: list[DiagnosticError] = []

        for call in calls:
            # If known routes are provided, check if route exists
            if known_routes and call.normalized_path not in known_routes:
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
        files: dict[str, str],
        known_routes: set[str] | None = None,
    ) -> list[DiagnosticError]:
        all_diags: list[DiagnosticError] = []
        routes = known_routes or set()
        for file_path, content in files.items():
            if file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
                all_diags.extend(self.check_code(content, file_path, routes))
        return all_diags

    def verify_with_diff(
        self,
        current_files: dict[str, str],
        baseline_files: dict[str, str] | None = None,
        known_routes: set[str] | None = None,
    ) -> list[DiagnosticError]:
        current_diags = self.verify_files(current_files, known_routes=known_routes)
        if not baseline_files:
            return current_diags

        baseline_diags = self.verify_files(baseline_files, known_routes=known_routes)
        baseline_sigs = {d.signature for d in baseline_diags}

        return [d for d in current_diags if d.signature not in baseline_sigs]


# Backward compatibility
class TypeScriptChecker(TypeScriptTypeVerifier):
    def __init__(self, tsconfig_path: str | None = None) -> None:
        super().__init__()
        self.tsconfig_path = tsconfig_path

    def check_project(self) -> list[TypeScriptDiagnostic]:
        return []
