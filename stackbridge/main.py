"""StackBridge CLI entry point."""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from stackbridge.core.graph import StackGraph
from stackbridge.mcp_server.formatter import ContextFormatter
from stackbridge.mcp_server.server import get_route_contract, trace_fullstack_path


def run_index(repo_path: str, output: Optional[str] = None, no_cache: bool = False) -> int:
    """Builds and exports the dependency graph with incremental caching."""
    from stackbridge.core.indexer import IncrementalIndexer

    repo = Path(repo_path).resolve()
    print(f"Indexing repository at {repo}...")
    indexer = IncrementalIndexer(repo_path=str(repo))
    graph, report = indexer.index(use_cache=not no_cache)

    out_path = Path(output) if output else repo / ".stackbridge" / "graph.json"
    graph.export_json(out_path)

    cache_info = f"[Cache: {report.cached_files_hit}/{report.total_files} hit, {report.modified_files} modified | {report.duration_ms:.2f}ms]"
    print(f"Indexed {graph.node_count} nodes and {graph.edge_count} edges. {cache_info}")
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


def run_ui(
    repo_path: str,
    host: str = "127.0.0.1",
    port: int = 3456,
    no_browser: bool = False,
    dry_run: bool = False,
) -> int:
    """Launches the interactive Web Visualizer."""
    from stackbridge.ui.server import create_ui_server, get_graph_data
    repo = Path(repo_path).resolve()
    print(f"Launching StackBridge Web Visualizer for {repo}...")
    graph_data = get_graph_data(repo)
    print(f"Indexed {len(graph_data['nodes'])} nodes and {len(graph_data['edges'])} edges.")
    url = f"http://localhost:{port}"
    print(f"StackBridge Web Visualizer running on {url}")

    if no_browser or dry_run:
        print("Running in non-browser dry-run mode. Visualizer initialized successfully.")
        return 0

    import webbrowser
    webbrowser.open(url)
    server = create_ui_server(repo_path=repo, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping StackBridge Web Visualizer.")
    return 0


def run_serve(transport: str = "stdio") -> int:
    """Runs the MCP server."""
    from stackbridge.mcp_server.server import mcp
    if transport == "stdio":
        if hasattr(mcp, "run"):
            try:
                mcp.run(transport="stdio")
            except TypeError:
                mcp.run()
        return 0
    else:
        print(f"Starting StackBridge MCP Server ({transport})...", file=sys.stderr)
        mcp.run(transport=transport)
        return 0


def run_init_agents(repo_path: str, output: Optional[str] = None) -> int:
    """Generates an AGENTS.md architecture and boundary guide for coding agents."""
    from stackbridge.core.agent_context import AgentContextGenerator

    repo = Path(repo_path).resolve()
    print(f"Generating AGENTS.md for repository at {repo}...")
    written_path = AgentContextGenerator.write_agents_md(repo_path=str(repo), output_path=output)
    print(f"AGENTS.md successfully generated at {written_path}")
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
    index_parser.add_argument("--no-cache", action="store_true", default=False, help="Bypass incremental cache and re-index all files")
    index_parser.add_argument("--force", "-f", dest="no_cache", action="store_true", default=False, help="Force full re-indexing and bypass cache")

    # init-agents command
    agents_parser = subparsers.add_parser("init-agents", help="Generate AGENTS.md architecture and boundary context guide")
    agents_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    agents_parser.add_argument("--output", "-o", default=None, help="Custom output path for generated AGENTS.md")

    # trace command
    trace_parser = subparsers.add_parser("trace", help="Trace full-stack blast radius for a model or route")
    trace_parser.add_argument("pos_target", nargs="?", default=None, help="Target symbol, model, or route to trace")
    trace_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    trace_parser.add_argument("--target", "-t", default=None, help="Target symbol, model, or route to trace")

    # guard command
    guard_parser = subparsers.add_parser("guard", help="Run full-stack boundary verification and route guard")
    guard_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    guard_parser.add_argument("--fail-on-error", action="store_true", default=False, help="Exit with non-zero code on error")

    # ui command
    ui_parser = subparsers.add_parser("ui", help="Launch interactive full-stack dependency visualizer")
    ui_parser.add_argument("--repo-path", "-r", default=".", help="Path to repository root")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host address to bind")
    ui_parser.add_argument("--port", "-p", type=int, default=3456, help="Port to bind")
    ui_parser.add_argument("--no-browser", action="store_true", default=False, help="Do not open browser automatically / dry-run mode")
    ui_parser.add_argument("--dry-run", action="store_true", default=False, help="Run dry run verification without blocking")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "stream"], help="Transport protocol (stdio, sse)")

    args = parser.parse_args()

    if args.command == "index":
        sys.exit(run_index(args.repo_path, args.output, getattr(args, "no_cache", False)))
    elif args.command == "init-agents":
        sys.exit(run_init_agents(args.repo_path, args.output))
    elif args.command == "trace":
        target = args.target or args.pos_target
        if not target:
            trace_parser.error("the following arguments are required: target (positional or --target/-t)")
        sys.exit(run_trace(args.repo_path, target))
    elif args.command == "guard":
        sys.exit(run_guard(args.repo_path, getattr(args, "fail_on_error", False)))
    elif args.command == "ui":
        sys.exit(run_ui(args.repo_path, args.host, args.port, getattr(args, "no_browser", False), getattr(args, "dry_run", False)))
    elif args.command == "serve":
        sys.exit(run_serve(getattr(args, "transport", "stdio")))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
