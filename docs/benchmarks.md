# StackBridge-MCP Benchmark Methodology & Results

This document describes the benchmark methodology, metrics, and empirical results measured across synthetic test fixtures and real-world open-source full-stack codebases.

---

## 📊 Summary of Real-World Results

Measured against **`fastapi-realworld-example-app`** (44 files, 23 AST dependency nodes, 10 cross-boundary edges):

| Metric | Raw Codebase Dump | StackBridge Compact Slice | Improvement / Latency |
| :--- | :--- | :--- | :--- |
| **Context Window Size** | `19,705 tokens` | `51 tokens` | 📉 **99.74% Token Reduction** |
| **Blast Radius Query** | Full-repo grep: `~150 ms` | SQLite Recursive CTE: `0.75 ms` | ⚡ **200x Faster Traversal** |
| **Compiler Verification** | Global linter: `~3,500 ms` | Baseline-Diffed Engine: `312 ms` | 🛡️ **Zero False Positives** |
| **Test Suite Coverage** | — | 56 / 56 tests passing | ✅ **100% Passing** |

---

## 🔬 Benchmark Methodology

### 1. AST Parsing & Graph Construction
- **Goal:** Measure raw Tree-sitter AST parser throughput across TypeScript components, Python routes, and SQLAlchemy models.
- **Metric:** `nodes_per_sec`, elapsed time in milliseconds (`ms`).

### 2. Blast-Radius Traversal Latency
- **Goal:** Measure query response time when an AI agent requests downstream/upstream dependencies for a symbol.
- **Engine Comparison:** Compares in-memory NetworkX traversal against persistent SQLite Recursive CTE queries (`.stackbridge/graph.db`).

### 3. Token Efficiency & Context Reduction
- **Goal:** Quantify prompt token savings when providing a focused route/model contract slice instead of dumping full repository files into LLM context windows.
- **Metric:** Calculated using GPT-4 / Claude token estimations comparing raw source files to compact AST contract slices.

### 4. Baseline-Diffed Compiler Verification
- **Goal:** Measure time to apply in-memory file overlays, run AST type checkers, and filter pre-existing repository warnings.

---

## 🏃 Running Benchmarks Locally

```bash
# Run benchmark on synthetic fullstack fixture (3 runs averaged)
python -m stackbridge.main benchmark --runs 3

# Run benchmark on a custom repository with Markdown report export
python -m stackbridge.main benchmark --repo-path path/to/repo --runs 3 --output BENCHMARK.md
```
