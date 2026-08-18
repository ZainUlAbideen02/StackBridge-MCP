# StackBridge-MCP Benchmark Results

> Automated benchmark suite measuring AST parsing, blast-radius traversal, compiler verification, and token reduction.

## 1. Executive Summary
- **Target Repository:** `C:\Users\youca\OneDrive\Desktop\StackBridge-MCP\tests\real_repos\realworld_app`
- **Benchmark Iterations:** 3 runs (averaged)
- **Total Suite Latency:** **624.60 ms**
- **Status:** 🟢 **4/4 Benchmarks Passed (100%)**

## 2. Performance & Latency Matrix

| Benchmark | Avg Latency | Min / Max Latency | Status | Key Metrics |
| :--- | :--- | :--- | :--- | :--- |
| **AST Parsing & Graph Construction** | `310.23 ms` | `297.80ms / 332.82ms` | 🟢 Passed | `nodes: 23`, `edges: 10`, `throughput_nodes_per_sec: 69.1` |
| **Blast-Radius Traversal Latency** | `0.75 ms` | `0.65ms / 0.87ms` | 🟢 Passed | `target: app/models/article.py::Article`, `found: True`, `affected_files_count: 4` |
| **Token Efficiency & Reduction** | `1.00 ms` | `1.00ms / 1.00ms` | 🟢 Passed | `raw_tokens: 19705`, `slice_tokens: 51`, `tokens_saved: 19654` |
| **Baseline-Diffed Compiler Verification** | `312.62 ms` | `302.64ms / 325.44ms` | 🟢 Passed | `has_breakage: False`, `error_count: 0`, `impacted_files: 1` |

## 3. Detailed Benchmark Breakdown

### ⚡ AST Parsing & Graph Construction
- **Latency:** `310.23 ms`
- **Details:** Parsed full-stack repo into 23 nodes and 10 edges in 332.82ms
- **Metrics:**
  * `nodes`: `23`
  * `edges`: `10`
  * `throughput_nodes_per_sec`: `69.11`

### ⚡ Blast-Radius Traversal Latency
- **Latency:** `0.75 ms`
- **Details:** Traced blast radius for 'app/models/article.py::Article' in 0.874ms (SQLite CTE: 0.705ms)
- **Metrics:**
  * `target`: `app/models/article.py::Article`
  * `found`: `True`
  * `affected_files_count`: `4`
  * `impacted_frontend_count`: `0`
  * `sqlite_cte_time_ms`: `0.705`
  * `networkx_time_ms`: `0.874`

### ⚡ Token Efficiency & Reduction
- **Latency:** `1.00 ms`
- **Details:** Reduced context from 19705 raw tokens to 51 tokens (99.74% savings)
- **Metrics:**
  * `raw_tokens`: `19705`
  * `slice_tokens`: `51`
  * `tokens_saved`: `19654`
  * `percentage_saved`: `99.74`

### ⚡ Baseline-Diffed Compiler Verification
- **Latency:** `312.62 ms`
- **Details:** Verified 1 impacted files in 309.79ms with 0 breakage diagnostics detected
- **Metrics:**
  * `has_breakage`: `False`
  * `error_count`: `0`
  * `impacted_files`: `1`
