<div align="center">

# 🌉 StackBridge-MCP

**Sub-1ms Cross-Stack AST Contract & Verification Layer for AI Coding Agents**

[![PyPI version](https://img.shields.io/pypi/v/stackbridge.svg)](https://pypi.org/project/stackbridge/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://pypi.org/project/stackbridge/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/ZainUlAbideen02/StackBridge-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/ZainUlAbideen02/StackBridge-MCP/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-56%2F56%20passing%20(100%25)-brightgreen.svg)](https://github.com/ZainUlAbideen02/StackBridge-MCP)
[![FastMCP Compatible](https://img.shields.io/badge/MCP-JSON--RPC%202.0-purple.svg)](https://modelcontextprotocol.io/)

<p align="center">
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-client-configuration">Client Config</a> •
  <a href="#-real-world-benchmarks">Benchmarks</a> •
  <a href="#-architecture--mcp-tools">MCP Tools</a> •
  <a href="#-cli-reference">CLI Reference</a> •
  <a href="docs/architecture.md">Docs</a>
</p>

</div>

---

## 💡 Why StackBridge?

When AI coding agents (**Cursor, Claude Code, Windsurf, Antigravity**) edit backend models or API routes in full-stack codebases, backend unit tests frequently pass while the frontend silently breaks in production:

1. An agent modifies an API parameter or Pydantic/SQLAlchemy field in `backend/routes.py`.
2. Backend tests pass in isolation. Nothing warns the agent.
3. The React/Next.js client calling that endpoint across the boundary fails with runtime errors.

**StackBridge-MCP** is an always-warm [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that parses full-stack AST relationships, discovers cross-stack blast radii in **0.75 ms**, and verifies changes using baseline-diffed compiler checks with zero false positives.

```
React / Next.js Client            FastAPI Routes            SQLAlchemy ORM Models
   (TypeScript AST)      ───►    (Python AST)     ───►          (Schema AST)
  UserProfile.tsx              get_user_billing()              BillingAccount
```

---

## ⚡ Key Highlights

- **🌲 Tree-sitter AST Graph:** Parses Next.js (`fetch`, Axios, React Query) ↔ FastAPI routes ↔ SQLAlchemy ORM models without heavy LSP sidecars or runtime imports.
- **⚡ Sub-1ms Traversal:** Persistent SQLite WAL database with recursive Common Table Expressions (**0.75 ms** traversal query latency).
- **📉 99.74% Prompt Token Reduction:** Replaces massive multi-file code dumps with compact, mathematically precise AST contract slices.
- **🛡️ Root-Cause Diagnostic Ranking:** Graph-distance BFS ranks errors (`🔴 PRIMARY ROOT CAUSE` vs `⚠️ CASCADING BREAKAGE`) and outputs immediate Git diff patches.
- **🧪 Test Impact Selection:** Isolates test suites impacted by a schema change and highlights untested blast-radius paths (0% coverage).
- **🌐 Interactive Canvas:** Built-in localhost tripartite visualizer (`stackbridge ui`) on `http://127.0.0.1:3456`.
- **🔄 Continuous Intelligence:** Background file watcher daemon (`stackbridge watch`) and living [`AGENTS.md`](AGENTS.md) context generator.

---

## 📊 Real-World Benchmarks

Empirical performance measured on [**`fastapi-realworld-example-app`**](https://github.com/adr1enbe4udou1n/fastapi-realworld-example-app) (44 files, 23 AST dependency nodes, 10 cross-boundary edges):

| Benchmark Metric | Raw Codebase Dump | StackBridge Compact Slice | Improvement / Latency |
| :--- | :--- | :--- | :--- |
| **Context Window Size** | `19,705 tokens` | `51 tokens` | 📉 **99.74% Token Reduction** |
| **Blast Radius Traversal** | Full-repo search: `~150 ms` | SQLite Recursive CTE: `0.75 ms` | ⚡ **200x Faster Traversal** |
| **Compiler Verification** | Global linter: `~3,500 ms` | Baseline-Diffed Engine: `312 ms` | 🛡️ **Zero False Positives** |
| **Automated Test Suite** | — | 56 / 56 tests passing | ✅ **100% Passing** |

*See full benchmark methodology in [`docs/benchmarks.md`](docs/benchmarks.md) and [`REAL_WORLD_BENCHMARK.md`](REAL_WORLD_BENCHMARK.md).*

---

## 🚀 Quick Start

### Option 1: Zero-Install Execution (Recommended via `uvx`)
```bash
uvx stackbridge serve
```

### Option 2: Pip Installation
```bash
pip install stackbridge
stackbridge serve
```

---

## ⚙️ Client Configuration

Connect StackBridge to your AI pair programmer over standard JSON-RPC 2.0 stdio:

### 1. Cursor (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "stackbridge": {
      "command": "uvx",
      "args": ["stackbridge", "serve"]
    }
  }
}
```

### 2. Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "stackbridge": {
      "command": "python",
      "args": ["-m", "stackbridge.main", "serve", "--transport", "stdio"]
    }
  }
}
```

---

## 🤖 MCP Tools Reference

StackBridge exposes high-ergonomics tools to coding agents:

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `trace_fullstack_path` | `symbol_or_path: str` | Traces the full-stack dependency chain: Frontend component ➔ API route ➔ Database model. |
| `get_route_contract` | `route_path: str` | Extracts HTTP methods, status codes, response models, and linked frontend fetch callers with confidence scores. |
| `verify_schema_change`| `modified_files: dict` | Runs in-memory compiler checks across impacted files, ranking root causes and proposing diff patches. |
| `get_stack_health` | `repo_path: str` | Returns real-time full-stack boundary stats, node counts, edge counts, and breakage drift status. |

---

## 💻 CLI Reference

```bash
# Index a repository and export the dependency graph
stackbridge index --repo-path . --force

# Trace blast radius for a model or route
stackbridge trace --target BillingAccount

# Run pre-commit boundary verification guard
stackbridge guard --fail-on-error

# Launch interactive tripartite web visualizer
stackbridge ui --port 3456

# Start continuous background watcher daemon
stackbridge watch

# Generate living AGENTS.md boundary architecture guide
stackbridge init-agents

# Execute performance and token reduction benchmarks
stackbridge benchmark --runs 3 --output BENCHMARK.md
```

---

## 📁 Repository Structure

```text
StackBridge-MCP/
├── .github/
│   ├── workflows/ci.yml         # CI pipeline (Python 3.10-3.13 on Ubuntu/Windows/macOS)
│   ├── ISSUE_TEMPLATE/          # Bug report and feature request issue templates
│   └── PULL_REQUEST_TEMPLATE.md # Standard PR checklist
├── docs/
│   ├── architecture.md          # Subsystem breakdown and Mermaid diagrams
│   ├── benchmarks.md            # Benchmark methodology and raw metrics
│   └── ast_extraction_spec.md   # Tree-sitter extractor grammar specifications
├── stackbridge/
│   ├── core/                    # Unified StackGraph, SQLite CTE store, watcher, route matcher
│   ├── parsers/                 # Tree-sitter parsers (TS fetch, Python routes, SQLAlchemy)
│   ├── verifier/                # Baseline-diffed verifier, root-cause ranker, test impact selector
│   ├── mcp_server/              # FastMCP stdio server and JSON-RPC tools
│   ├── benchmarks/              # Benchmark runner and markdown report generator
│   └── ui/                      # Localhost tripartite interactive canvas
├── tests/                       # 56 automated test suites (parsers, verifiers, MCP E2E, CTE)
├── AGENTS.md                    # Living agent architecture guide
├── CHANGELOG.md                 # Version release notes
├── CONTRIBUTING.md              # Contribution and development guidelines
├── LICENSE                      # MIT License
└── pyproject.toml               # Package metadata and tool configurations
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
