# StackBridge-MCP Benchmark Results

> Automated benchmark suite measuring AST parsing, blast-radius traversal, compiler verification, and token reduction.

## 1. Executive Summary
- **Target Repository:** `C:\Users\youca\OneDrive\Desktop\StackBridge-MCP\tests\fixtures\synthetic_fullstack`
- **Benchmark Iterations:** 3 runs (averaged)
- **Total Suite Latency:** **21.73 ms**
- **Status:** 🟢 **4/4 Benchmarks Passed (100%)**

## 2. Performance & Latency Matrix

| Benchmark | Avg Latency | Min / Max Latency | Status | Key Metrics |
| :--- | :--- | :--- | :--- | :--- |
| **AST Parsing & Graph Construction** | `7.49 ms` | `5.51ms / 10.65ms` | 🟢 Passed | `nodes: 6`, `edges: 5`, `throughput_nodes_per_sec: 563.3` |
| **Blast-Radius Traversal Latency** | `0.26 ms` | `0.17ms / 0.44ms` | 🟢 Passed | `target: backend/models.py::BillingAccount`, `found: True`, `affected_files_count: 3` |
| **Token Efficiency & Reduction** | `1.00 ms` | `1.00ms / 1.00ms` | 🟢 Passed | `raw_tokens: 1062`, `slice_tokens: 52`, `tokens_saved: 1010` |
| **Baseline-Diffed Compiler Verification** | `12.98 ms` | `11.13ms / 16.26ms` | 🟢 Passed | `has_breakage: True`, `error_count: 1`, `impacted_files: 3` |

## 3. Detailed Benchmark Breakdown

### ⚡ AST Parsing & Graph Construction
- **Latency:** `7.49 ms`
- **Details:** Parsed full-stack repo into 6 nodes and 5 edges in 10.65ms
- **Metrics:**
  * `nodes`: `6`
  * `edges`: `5`
  * `throughput_nodes_per_sec`: `563.28`

### ⚡ Blast-Radius Traversal Latency
- **Latency:** `0.26 ms`
- **Details:** Traced blast radius for backend/models.py::BillingAccount in 0.436ms
- **Metrics:**
  * `target`: `backend/models.py::BillingAccount`
  * `found`: `True`
  * `affected_files_count`: `3`
  * `impacted_frontend_count`: `1`

### ⚡ Token Efficiency & Reduction
- **Latency:** `1.00 ms`
- **Details:** Reduced context from 1062 raw tokens to 52 tokens (95.1% savings)
- **Metrics:**
  * `raw_tokens`: `1062`
  * `slice_tokens`: `52`
  * `tokens_saved`: `1010`
  * `percentage_saved`: `95.1`

### ⚡ Baseline-Diffed Compiler Verification
- **Latency:** `12.98 ms`
- **Details:** Verified 3 impacted files in 16.26ms with 1 breakage diagnostics detected
- **Metrics:**
  * `has_breakage`: `True`
  * `error_count`: `1`
  * `impacted_files`: `3`
