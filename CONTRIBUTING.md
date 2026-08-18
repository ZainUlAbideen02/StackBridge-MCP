# Contributing to StackBridge-MCP

Thank you for your interest in contributing to **StackBridge-MCP**! We welcome bug reports, feature proposals, parser enhancements, and performance optimizations.

---

## 🛠️ Development Setup

### 1. Prerequisites
- Python 3.10+
- Git

### 2. Clone and Setup Environment
```bash
# Clone repository
git clone https://github.com/ZainUlAbideen02/StackBridge-MCP.git
cd StackBridge-MCP

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate

# Install package in editable mode with development dependencies
pip install -e ".[dev]"
```

---

## 🧪 Testing & Verification

StackBridge maintains a 100% passing test suite covering unit tests, AST parsers, MCP server JSON-RPC communications, and resilience benchmarks.

```bash
# Run complete test suite
pytest -v

# Run standalone mock JSON-RPC MCP client test
python scripts/test_mcp_client.py

# Run benchmark suite
python -m stackbridge.benchmarks.benchmark_runner

# Run linting and type checks
ruff check .
mypy stackbridge/
```

---

## 📐 Architecture Guidelines

1. **Deterministic AST Extraction**: Parsers in `stackbridge/parsers/` must use Tree-sitter AST queries without requiring runtime imports or heavy LSP sidecars.
2. **Zero False Positives**: Verifier engines in `stackbridge/verifier/` must baseline-diff errors so pre-existing codebase warnings are filtered out.
3. **Sub-millisecond Traversal**: Dependency graph queries in `stackbridge/core/` must leverage SQLite WAL mode and recursive Common Table Expressions (CTEs).
4. **FastMCP Compatibility**: All MCP tools in `stackbridge/mcp_server/` must expose typed parameters and return compact markdown/JSON payloads.

---

## 📬 Pull Request Process

1. Fork the repository and create your feature branch: `git checkout -b feature/amazing-feature`.
2. Commit your changes: `git commit -m "feat(parser): add support for Axios instance baseURL"`.
3. Ensure all tests and benchmarks pass: `pytest -v`.
4. Open a Pull Request referencing any related issues using the PR template.
