# StackBridge MCP

A local Model Context Protocol (MCP) server that traces full-stack dependencies across Next.js (TypeScript) `fetch` calls, FastAPI (Python) route handlers, and SQLAlchemy models with compiler-verified breakage detection.

## Features
- **TypeScript AST Parser**: Extracts route endpoints, parameters, and payloads from Next.js / React components using tree-sitter.
- **FastAPI Route Parser**: Extracts route paths, HTTP methods, and parameter schemas from Python route definitions.
- **SQLAlchemy Model Parser**: Maps ORM models and relationships to route handlers and DB queries.
- **Dependency Graph**: Constructs cross-stack dependency graphs using `networkx`.
- **MCP Server**: Exposes tools and resources for AI assistants to inspect full-stack relationships and detect breaking changes across frontend and backend boundaries.

## Setup & Installation

```bash
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

## Testing & Validation

```bash
# Run the mock MCP client verification test
python scripts/test_mcp_client.py

# Run the complete test suite
pytest -v
```

