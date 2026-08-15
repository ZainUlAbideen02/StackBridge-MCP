"""StackBridge CLI entry point."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from stackbridge.core.graph import StackGraph
from stackbridge.mcp_server.formatter import ContextFormatter
from stackbridge.mcp_server.server import get_route_contract, trace_fullstack_path


def run_index(repo_path: str, output: Optional[str] = None) -> int:
    """Builds and exports the dependency graph."""
    repo = Path(repo_path).resolve()
    print(f"Indexing repository at {repo}...")
    graph = StackGraph.build_from_repo(str(repo))

    out_path = Path(output) if output else repo / ".stackbridge" / "graph.json"
    graph.export_json(out_path)
    print(f"Indexed {graph.node_count} nodes and {graph.edge_count} edges.")
    print(f"Graph written to {out_path}")
    return 0


def run_trace(repo_path: str, target: str) -> int:
    """Traces full-stack dependencies for a target symbol or route."""
    repo = Path(repo_path).resolve()
    print(f"Tracing dependencies for '{target}' in {repo}...")
    result = trace_fullstack_path(repo_path=str(repo), target=target)

    formatted = ContextFormatter.format_trace_result(result)
    print("\n" + formatted)
    return 0


def run_guard(repo_path: str, fail_on_error: bool = False) -> int:
    """Runs full-stack boundary verification and route guard."""
    from stackbridge.verifier.guard import StackGuardEngine
    repo = Path(repo_path).resolve()
    print(f"Running StackBridge Guard on repository: {repo}...")
    guard = StackGuardEngine(repo_path=repo)
    report = guard.check_repo()

    print("=" * 80)
    print("  StackBridge Guard Verification Summary")
    print("=" * 80)
    print(f"  Impacted / Verified Files: {len(report.verified_files)}")
    print(f"  Diagnostics Found:         {report.error_count}")
    print(f"  Status:                    {'BREAKAGE DETECTED' if report.has_breakage else 'PASSED (Clean)'}")
    print("=" * 80)

    if report.has_breakage:
        for diag in report.diagnostics:
            print(f"  - [{diag.source.upper()}] {diag.file_path}:{diag.line} - {diag.message}")
        if fail_on_error:
            return 1

    return 0


def run_serve() -> int:
    """Runs the MCP server."""
    from stackbridge.mcp_server.server import mcp
    print("Starting StackBridge MCP Server...")
    mcp.run()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stackbridge",
        description="StackBridge: Cross-stack dependency tracer between Next.js, FastAPI, and SQLAlchemy.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index command
    index_parser = subparsers.add_parser("index", help="Index repository and generate dependency graph")
    index_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    index_parser.add_argument("--output", "-o", default=None, help="Output path for serialized graph JSON")

    # trace command
    trace_parser = subparsers.add_parser("trace", help="Trace full-stack dependency chains")
    trace_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    trace_parser.add_argument("--target", "-t", required=True, help="Target symbol, model, or route to trace")

    # guard command
    guard_parser = subparsers.add_parser("guard", help="Run full-stack boundary verification and route guard")
    guard_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    guard_parser.add_argument("--fail-on-error", action="store_true", default=False, help="Exit with non-zero code on error")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")

    args = parser.parse_args()

    if args.command == "index":
        sys.exit(run_index(args.repo_path, args.output))
    elif args.command == "trace":
        sys.exit(run_trace(args.repo_path, args.target))
    elif args.command == "guard":
        sys.exit(run_guard(args.repo_path, getattr(args, "fail_on_error", False)))
    elif args.command == "serve":
        sys.exit(run_serve())
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
