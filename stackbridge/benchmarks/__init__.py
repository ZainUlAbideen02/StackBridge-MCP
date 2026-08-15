"""Benchmarking suite for StackBridge MCP."""

__all__ = ["BenchmarkResult", "BenchmarkSuite"]


def __getattr__(name: str):
    if name in ("BenchmarkResult", "BenchmarkSuite"):
        from stackbridge.benchmarks.benchmark_runner import (
            BenchmarkResult,
            BenchmarkSuite,
        )
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
