"""Context formatting and token reduction utility for LLM prompt delivery."""

import json
from typing import Any


class ContextFormatter:
    """Formats full-stack traces and route contracts into dense, token-efficient context slices."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Approximates token count (avg ~4 chars / token or 0.75 words / token)."""
        if not text:
            return 0
        return max(1, int(len(text) / 3.8))

    @classmethod
    def calculate_token_savings(
        cls,
        raw_full_files: dict[str, str],
        compact_slice_data: Any,
    ) -> dict[str, Any]:
        """Calculates token savings between raw full source files vs. targeted compact slice."""
        raw_combined = "\n".join(raw_full_files.values())
        raw_tokens = cls.estimate_tokens(raw_combined)

        if isinstance(compact_slice_data, str):
            slice_text = compact_slice_data
        else:
            slice_text = json.dumps(compact_slice_data, indent=2)

        slice_tokens = cls.estimate_tokens(slice_text)
        tokens_saved = max(0, raw_tokens - slice_tokens)
        percentage_saved = round((tokens_saved / raw_tokens * 100), 2) if raw_tokens > 0 else 0.0

        return {
            "raw_tokens": raw_tokens,
            "slice_tokens": slice_tokens,
            "tokens_saved": tokens_saved,
            "percentage_saved": percentage_saved,
        }

    @classmethod
    def format_trace_result(cls, trace_data: dict[str, Any]) -> str:
        """Formats a fullstack trace result into markdown for AI context injection."""
        lines = [
            f"### Full-Stack Dependency Trace: `{trace_data.get('target', 'unknown')}`",
            "",
        ]
        
        chains = trace_data.get("chains", [])
        if chains:
            lines.append("#### Dependency Chains:")
            for chain in chains:
                lines.append(f"- `{' -> '.join(chain)}`")
            lines.append("")

        impacted_files = trace_data.get("impacted_files", [])
        if impacted_files:
            lines.append(f"**Impacted Files ({len(impacted_files)}):**")
            for f in impacted_files:
                lines.append(f"- `{f}`")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def format_route_contract(cls, contract_data: dict[str, Any]) -> str:
        """Formats an endpoint contract and linked frontend callers."""
        lines = [
            f"### Route Contract: `{contract_data.get('route_path', 'unknown')}`",
            f"- **Method:** `{contract_data.get('http_method', 'GET')}`",
            f"- **Handler:** `{contract_data.get('handler_name', 'unknown')}`",
            f"- **Response Model:** `{contract_data.get('response_model', 'None')}`",
            "",
            "#### Linked Callers:",
        ]

        for caller in contract_data.get("linked_callers", []):
            conf = caller.get("confidence", 1.0)
            file_loc = f"{caller.get('file_path')}:{caller.get('line')}"
            lines.append(f"- `{file_loc}` (Confidence: `{conf}`)")

        return "\n".join(lines)
