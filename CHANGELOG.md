# Changelog

All notable changes to **StackBridge-MCP** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-08-18

### 🚀 Initial Public Release

#### ⚡ Core Engine & Graph Architecture
- **Tree-sitter AST Parsers:** Full-stack AST extraction for TypeScript/React (`fetch`, Axios, React Query), Python FastAPI route decorators (`@app.get`, `@router.post`, sub-router prefix chaining), and SQLAlchemy ORM models (`Column`, `relationship`).
- **Tripartite Dependency Graph:** Bidirectional AST linking between UI components, API route handlers, and database models.
- **Enterprise SQLite WAL Store:** High-performance local cache with recursive Common Table Expression (CTE) graph traversal executing in under 1 ms (`0.75 ms` verified).
- **Two-Tier Mtime & SHA-256 Invalidation:** Git-diff delta indexer avoiding redundant full-codebase scans.

#### 🛡️ Compiler Verification & Guard Engine
- **Baseline-Diffed Type Verification:** Eliminates false positives by filtering baseline codebase warnings and isolating newly introduced breaking changes.
- **Root-Cause Diagnostic Ranking:** Graph-distance BFS ranks errors (`🔴 PRIMARY ROOT CAUSE` vs `⚠️ CASCADING BREAKAGE`) and outputs clean Git diff patch recommendations.
- **Test Impact Selection:** Maps AST paths to test files and isolates impacted suites with 0% unverified coverage warnings.
- **Daemon Resilience:** Concurrency locking with `threading.Lock`, strict 6.0s timeout enforcement, and automatic daemon respawn (`DAEMON_RECOVERED`).

#### 🤖 FastMCP Protocol Server
- Standard JSON-RPC 2.0 stdio MCP server for Cursor, Claude Code, Windsurf, and Antigravity.
- Tools:
  - `trace_fullstack_path(symbol_or_path)`
  - `get_route_contract(route_path)`
  - `verify_schema_change(modified_files)`
  - `verify_breakage(modified_files)`
  - `get_stack_health()`

#### 📊 Visualizer & Tooling
- **Localhost Tripartite Visualizer:** Interactive Vis-Network dependency graph on `http://127.0.0.1:3456` (`stackbridge ui`).
- **Continuous Watcher Daemon:** Background file watcher keeping `.stackbridge/graph.db` continuously warm (`stackbridge watch`).
- **Agent Architecture Guide:** Automatic `AGENTS.md` context generator (`stackbridge init-agents`).
- **Benchmark Suite:** Automated performance benchmark harness (`stackbridge benchmark`).
