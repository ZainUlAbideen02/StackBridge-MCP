"""Agent Diagnostic Formatter generating ergonomic, actionable Markdown for AI coding agents."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from stackbridge.verifier.py_checker import DiagnosticError


class AgentDiagnosticFormatter:
    """Formats full-stack AST compiler errors and diagnostics into structured, token-dense Markdown for LLM agents."""

    @staticmethod
    def _extract_snippet(file_path: str, error_line: int, repo_path: str = ".") -> str:
        """Extracts a 3-line context window around error_line with a '>' line pointer."""
        resolved = Path(repo_path) / file_path if not os.path.isabs(file_path) else Path(file_path)
        if not resolved.exists():
            # Try relative directly
            resolved = Path(file_path)
            if not resolved.exists():
                return f"{error_line} | (Source file '{file_path}' not accessible)"

        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            return f"{error_line} | (Error reading file content)"

        if not lines:
            return f"{error_line} | (File is empty)"

        total_lines = len(lines)
        target_idx = max(0, min(total_lines - 1, error_line - 1))
        start_idx = max(0, target_idx - 1)
        end_idx = min(total_lines, target_idx + 2)

        formatted_snippet: List[str] = []
        for idx in range(start_idx, end_idx):
            line_num = idx + 1
            line_content = lines[idx].rstrip("\r\n")
            prefix = ">" if line_num == error_line else " "
            formatted_snippet.append(f"{prefix} {line_num:4d} | {line_content}")

        return "\n".join(formatted_snippet)

    @staticmethod
    def _generate_suggested_fix(diag: Union[DiagnosticError, Dict[str, Any]]) -> str:
        """Generates specific, actionable remediation steps for AI pair-programmers."""
        msg = diag.message if isinstance(diag, DiagnosticError) else diag.get("message", "")
        rule = (diag.rule if isinstance(diag, DiagnosticError) else diag.get("rule", "")) or ""
        file_path = diag.file_path if isinstance(diag, DiagnosticError) else diag.get("file_path", "")

        if "schema-attribute-missing" in rule or "does not exist on model" in msg:
            return (
                f"- **Model Schema Alignment**: Restore or declare the referenced field in the SQLAlchemy ORM model definition, "
                f"or update caller in `{file_path}` to access valid declared column attributes."
            )
        elif "unmatched-fetch-route" in rule or "does not match any registered" in msg:
            return (
                f"- **Route Contract Fix**: Ensure the URL path pattern in `{file_path}` matches the FastAPI router prefix "
                f"and endpoint path definition, or register the missing `@router` endpoint."
            )
        elif "type" in rule.lower() or "type" in msg.lower():
            return (
                f"- **Type Signature Compatibility**: Align frontend TypeScript payload type definitions with backend "
                f"Pydantic request/response models."
            )
        else:
            return (
                f"- **Remediation**: Inspect `{file_path}` around the highlighted error site and ensure schema definitions "
                f"and parameter contracts are synchronized across full-stack boundaries."
            )

    @classmethod
    def format_breakage_report(
        cls,
        diagnostics: List[Union[DiagnosticError, Dict[str, Any]]],
        graph_nodes: Optional[List[Any]] = None,
        repo_path: str = ".",
    ) -> str:
        """
        Formats compiler errors into high-ergonomics Markdown for coding agents:
        - 🔴 BREAKING: Type/payload errors breaking callers.
        - 🟡 DRIFT: Missing fields or altered schemas.
        - 🟢 SAFE: No breakages detected.
        """
        if not diagnostics:
            return (
                "## 🟢 SAFE: Full-Stack Boundaries Verified\n\n"
                "- **Status**: Clean (0 breaking changes detected)\n"
                "- **Verification**: All frontend fetch calls, API routes, and ORM model schemas match without type drift.\n"
            )

        breaking_items: List[Union[DiagnosticError, Dict[str, Any]]] = []
        drift_items: List[Union[DiagnosticError, Dict[str, Any]]] = []

        for d in diagnostics:
            sev = (d.severity if isinstance(d, DiagnosticError) else d.get("severity", "error")).lower()
            rule = (d.rule if isinstance(d, DiagnosticError) else d.get("rule", "")).lower()
            if sev == "warning" or "drift" in rule or "deprecated" in rule:
                drift_items.append(d)
            else:
                breaking_items.append(d)

        output_lines: List[str] = []

        # Overall Status Header
        if breaking_items:
            output_lines.append(f"## 🔴 BREAKING: {len(breaking_items)} Cross-Stack Compiler Error(s) Detected\n")
            output_lines.append("> **Action Required**: Schema modifications break downstream route handlers or frontend caller contracts.\n")
        else:
            output_lines.append(f"## 🟡 DRIFT: {len(drift_items)} Schema Drift Warning(s) Detected\n")
            output_lines.append("> **Review Advisory**: Non-breaking contract shifts detected across boundaries.\n")

        # Format Breaking Errors
        if breaking_items:
            output_lines.append("### 🔴 BREAKING: Critical Compiler Errors\n")
            for idx, item in enumerate(breaking_items, start=1):
                fpath = item.file_path if isinstance(item, DiagnosticError) else item.get("file_path", "")
                line = item.line if isinstance(item, DiagnosticError) else item.get("line", 1)
                msg = item.message if isinstance(item, DiagnosticError) else item.get("message", "")
                rule = item.rule if isinstance(item, DiagnosticError) else item.get("rule", "compiler-error")

                snippet = cls._extract_snippet(fpath, line, repo_path=repo_path)
                fix = cls._generate_suggested_fix(item)

                output_lines.append(f"#### Error {idx}: `{rule}` in `{fpath}:{line}`")
                output_lines.append(f"**Diagnostic**: {msg}\n")
                output_lines.append("```python")
                output_lines.append(snippet)
                output_lines.append("```\n")
                output_lines.append(f"**Suggested Fix**:\n{fix}\n")

        # Format Drift Warnings
        if drift_items:
            output_lines.append("### 🟡 DRIFT: Schema Drift Warnings\n")
            for idx, item in enumerate(drift_items, start=1):
                fpath = item.file_path if isinstance(item, DiagnosticError) else item.get("file_path", "")
                line = item.line if isinstance(item, DiagnosticError) else item.get("line", 1)
                msg = item.message if isinstance(item, DiagnosticError) else item.get("message", "")
                rule = item.rule if isinstance(item, DiagnosticError) else item.get("rule", "schema-drift")

                snippet = cls._extract_snippet(fpath, line, repo_path=repo_path)
                fix = cls._generate_suggested_fix(item)

                output_lines.append(f"#### Warning {idx}: `{rule}` in `{fpath}:{line}`")
                output_lines.append(f"**Notice**: {msg}\n")
                output_lines.append("```python")
                output_lines.append(snippet)
                output_lines.append("```\n")
                output_lines.append(f"**Suggested Action**:\n{fix}\n")

        return "\n".join(output_lines)

    @classmethod
    def format_trace_report(cls, trace_data: Dict[str, Any]) -> str:
        """Formats fullstack dependency trace into structured Markdown for AI agents."""
        target = trace_data.get("target", "Target")
        found = trace_data.get("found", False)
        chains = trace_data.get("chains", [])
        impacted_files = trace_data.get("impacted_files", [])

        if not found:
            return f"## ⚠️ Symbol Not Found\n\nTarget `{target}` was not located in dependency graph."

        lines = [
            f"## 🔗 StackBridge Trace: `{target}`\n",
            f"- **Impacted Files ({len(impacted_files)})**: {', '.join(impacted_files) if impacted_files else 'None'}",
            f"- **Dependency Chains Identified**: {len(chains)}\n",
            "### Dependency Paths:",
        ]

        for idx, chain in enumerate(chains, start=1):
            arrow_path = " ➔ ".join(f"`{node}`" for node in chain)
            lines.append(f"{idx}. {arrow_path}")

        return "\n".join(lines)
