"""Tests for the StackBridge benchmark suite."""

from pathlib import Path
import pytest

from stackbridge.benchmarks.benchmark_runner import BenchmarkSuite


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"


def test_benchmark_suite_run_all():
    suite = BenchmarkSuite(repo_path=str(FIXTURES_DIR))
    summary = suite.run_all()

    assert summary["suite"] == "StackBridge MCP Benchmark Suite"
    assert summary["total_benchmarks"] == 4
    assert summary["passed"] == 4
    assert summary["total_time_ms"] > 0
    assert len(summary["results"]) == 4

    # Verify individual benchmark metrics
    graph_res = next(r for r in summary["results"] if r["name"] == "AST Parsing & Graph Construction")
    assert graph_res["status"] == "passed"
    assert graph_res["metrics"]["nodes"] >= 6
    assert graph_res["metrics"]["edges"] >= 5

    blast_res = next(r for r in summary["results"] if r["name"] == "Blast-Radius Traversal Latency")
    assert blast_res["status"] == "passed"
    assert blast_res["metrics"]["found"] is True

    token_res = next(r for r in summary["results"] if r["name"] == "Token Efficiency & Reduction")
    assert token_res["status"] == "passed"
    assert token_res["metrics"]["percentage_saved"] > 50.0

    verifier_res = next(r for r in summary["results"] if r["name"] == "Baseline-Diffed Compiler Verification")
    assert verifier_res["status"] == "passed"
    assert verifier_res["metrics"]["has_breakage"] is True


def test_benchmark_suite_default_path_and_reporter(capsys):
    from stackbridge.benchmarks.benchmark_runner import print_benchmark_report
    suite = BenchmarkSuite()
    assert suite.repo_path.exists()

    summary = suite.run_all()
    print_benchmark_report(summary)
    captured = capsys.readouterr()
    assert "StackBridge MCP Benchmark Suite" in captured.out
    assert "Passed" in captured.out
