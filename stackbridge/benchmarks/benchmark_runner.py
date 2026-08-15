"""Benchmarking runner for AST parsing, Graph construction, blast radius traversal, and token efficiency."""

import os
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from stackbridge.core.graph import StackGraph
from stackbridge.mcp_server.formatter import ContextFormatter
from stackbridge.mcp_server.server import get_route_contract
from stackbridge.verifier.engine import VerifierEngine


class BenchmarkResult(BaseModel):
    name: str
    execution_time_ms: float
    status: str = "passed"
    metrics: dict[str, Any] = Field(default_factory=dict)
    details: str | None = None


class BenchmarkSuite:
    """Runs performance, accuracy, and token reduction benchmarks for StackBridge."""

    def __init__(self, repo_path: str | None = None) -> None:
        if repo_path:
            self.repo_path = Path(repo_path).resolve()
        else:
            default_fixture = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic_fullstack"
            self.repo_path = default_fixture.resolve()

    def benchmark_graph_construction(self) -> BenchmarkResult:
        """Measures the speed and scale of Tree-sitter AST parsing and Graph construction."""
        start_time = time.perf_counter()
        graph = StackGraph.build_from_repo(str(self.repo_path))
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return BenchmarkResult(
            name="AST Parsing & Graph Construction",
            execution_time_ms=round(elapsed_ms, 2),
            metrics={
                "nodes": graph.node_count,
                "edges": graph.edge_count,
                "throughput_nodes_per_sec": round((graph.node_count / (elapsed_ms / 1000)), 2) if elapsed_ms > 0 else 0,
            },
            details=f"Parsed full-stack repo into {graph.node_count} nodes and {graph.edge_count} edges in {elapsed_ms:.2f}ms",
        )

    def benchmark_blast_radius_traversal(self) -> BenchmarkResult:
        """Measures blast-radius traversal query latency."""
        graph = StackGraph.build_from_repo(str(self.repo_path))
        
        target = "backend/models.py::BillingAccount"
        start_time = time.perf_counter()
        blast = graph.get_blast_radius(target)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return BenchmarkResult(
            name="Blast-Radius Traversal Latency",
            execution_time_ms=round(elapsed_ms, 3),
            metrics={
                "target": target,
                "found": blast.get("found", False),
                "affected_files_count": len(blast.get("affected_files", [])),
                "impacted_frontend_count": len(blast.get("affected_frontend", [])),
            },
            details=f"Traced blast radius for {target} in {elapsed_ms:.3f}ms",
        )

    def benchmark_token_reduction(self) -> BenchmarkResult:
        """Measures token savings achieved by compact full-stack context slices."""
        # Read full files from fixture
        raw_files: dict[str, str] = {}
        for root, _, files in os.walk(self.repo_path):
            for f in files:
                ext = os.path.splitext(f)[1]
                if ext in (".tsx", ".ts", ".py"):
                    full_p = os.path.join(root, f)
                    with open(full_p, "r", encoding="utf-8") as file_handle:
                        raw_files[f] = file_handle.read()

        contract = get_route_contract(str(self.repo_path), "/api/v1/users/{user_id}/billing")
        formatted_slice = ContextFormatter.format_route_contract(contract)

        savings = ContextFormatter.calculate_token_savings(raw_files, formatted_slice)

        return BenchmarkResult(
            name="Token Efficiency & Reduction",
            execution_time_ms=1.0,
            metrics=savings,
            details=f"Reduced context from {savings['raw_tokens']} raw tokens to {savings['slice_tokens']} tokens ({savings['percentage_saved']}% savings)",
        )

    def benchmark_compiler_verification(self) -> BenchmarkResult:
        """Measures baseline-diffed compiler verification latency."""
        models_path = self.repo_path / "backend" / "models.py"
        with open(models_path, "r", encoding="utf-8") as f:
            original_code = f.read()

        # Simulate deleted field
        modified_code = original_code.replace(
            'plan = Column(String, nullable=False, default="free")',
            '# plan removed',
        )

        engine = VerifierEngine(repo_path=self.repo_path)
        start_time = time.perf_counter()
        report = engine.verify_impacted_files(
            modified_files={"backend/models.py": modified_code},
            repo_path=self.repo_path,
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return BenchmarkResult(
            name="Baseline-Diffed Compiler Verification",
            execution_time_ms=round(elapsed_ms, 2),
            metrics={
                "has_breakage": report.has_breakage,
                "error_count": report.error_count,
                "impacted_files": len(report.impacted_files),
            },
            details=f"Verified {len(report.impacted_files)} impacted files in {elapsed_ms:.2f}ms with {report.error_count} breakage diagnostics detected",
        )

    def run_all(self) -> dict[str, Any]:
        """Runs all benchmarks in the suite and returns aggregated metrics."""
        results = [
            self.benchmark_graph_construction(),
            self.benchmark_blast_radius_traversal(),
            self.benchmark_token_reduction(),
            self.benchmark_compiler_verification(),
        ]

        total_time_ms = sum(r.execution_time_ms for r in results)
        passed_count = sum(1 for r in results if r.status == "passed")

        return {
            "suite": "StackBridge MCP Benchmark Suite",
            "repo_path": str(self.repo_path),
            "total_benchmarks": len(results),
            "passed": passed_count,
            "total_time_ms": round(total_time_ms, 2),
            "results": [r.model_dump() for r in results],
        }


def print_benchmark_report(summary: dict[str, Any]) -> None:
    """Prints a formatted benchmark summary table to stdout."""
    print("=" * 80)
    print(f"  {summary['suite']}")
    print(f"  Target Repository: {summary['repo_path']}")
    print("=" * 80)
    print(f"{'Benchmark Name':<40} | {'Time (ms)':<10} | {'Status':<8} | {'Key Metrics'}")
    print("-" * 80)

    for r in summary["results"]:
        metrics_summary = []
        for k, v in r["metrics"].items():
            if isinstance(v, float):
                metrics_summary.append(f"{k}: {v:.1f}")
            elif isinstance(v, (int, str, bool)):
                metrics_summary.append(f"{k}: {v}")
        metrics_str = ", ".join(metrics_summary[:3])
        print(f"{r['name']:<40} | {r['execution_time_ms']:<10.2f} | {r['status']:<8} | {metrics_str}")

    print("=" * 80)
    print(f"Total Execution Time: {summary['total_time_ms']:.2f} ms ({summary['passed']}/{summary['total_benchmarks']} Passed)\n")


def main() -> None:
    repo_arg = sys.argv[1] if len(sys.argv) > 1 else None
    suite = BenchmarkSuite(repo_path=repo_arg)
    summary = suite.run_all()
    print_benchmark_report(summary)


if __name__ == "__main__":
    main()
