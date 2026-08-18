"""Predictive Test Impact Selector for Full-Stack Repositories."""

import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from stackbridge.core.graph import StackGraph
from stackbridge.core.models import BackendRoute, ORMModel


class TestImpactSelector:
    """Selects and maps test suites impacted by changes to backend routes, ORM models, or frontend components."""

    __test__ = False

    TEST_PATTERNS = [
        r"^test_.*\.py$",
        r".*_test\.py$",
        r".*\.test\.(?:js|jsx|ts|tsx)$",
        r".*\.spec\.(?:js|jsx|ts|tsx)$",
    ]

    def __init__(
        self,
        repo_path: Union[str, Path] = ".",
        graph: Optional[StackGraph] = None,
    ) -> None:
        self.repo_dir = Path(repo_path).resolve()
        self._graph = graph

    @property
    def graph(self) -> StackGraph:
        if self._graph is None:
            self._graph = StackGraph.build_from_repo(str(self.repo_dir))
        return self._graph

    def discover_tests(self) -> List[str]:
        """Discovers all test files in the repository."""
        test_files: List[str] = []
        compiled_patterns = [re.compile(p) for p in self.TEST_PATTERNS]

        for root, dirs, files in os.walk(self.repo_dir):
            dirs[:] = [
                d for d in dirs
                if d not in (".git", "node_modules", ".venv", "venv", "__pycache__", ".gemini", ".pytest_cache", "coverage", "build", "dist")
            ]
            for f in files:
                if any(cp.match(f) for cp in compiled_patterns):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, self.repo_dir).replace("\\", "/")
                    test_files.append(rel_p)

        test_files.sort()
        return test_files

    def map_tests_to_routes(self) -> Dict[str, List[str]]:
        """
        Maps every backend route ID and normalized path to the test files that reference it.
        Returns a dict: {route_id: [test_file_path, ...]}
        """
        graph_dict = self.graph.to_dict()
        routes = [n for n in graph_dict.get("nodes", []) if n.get("type") in ("route", "api_route")]
        test_files = self.discover_tests()

        # Cache test file contents
        test_contents: Dict[str, str] = {}
        for tf in test_files:
            full_path = self.repo_dir / tf
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    test_contents[tf] = f.read()
            except Exception:
                test_contents[tf] = ""

        route_to_tests: Dict[str, List[str]] = {}

        for r in routes:
            r_id = r["id"]
            func_name = r.get("function_name", "")
            raw_path = r.get("raw_path", "")
            norm_path = r.get("normalized_path", "")

            matched_tests: Set[str] = set()

            # Search tokens
            tokens_to_search = set()
            if func_name and len(func_name) > 3:
                tokens_to_search.add(func_name)
            if raw_path and raw_path != "/":
                tokens_to_search.add(raw_path)
            if norm_path and norm_path != "/":
                tokens_to_search.add(norm_path)

            for tf, content in test_contents.items():
                # Direct file path reference
                if r.get("file_path") and r["file_path"] in content:
                    matched_tests.add(tf)
                    continue

                for token in tokens_to_search:
                    if token in content:
                        matched_tests.add(tf)
                        break

            route_to_tests[r_id] = sorted(list(matched_tests))

        return route_to_tests

    def get_untested_routes(self) -> List[str]:
        """Identifies all routes that have no matching test callers in any discovered test file."""
        mapping = self.map_tests_to_routes()
        return [route_id for route_id, tests in mapping.items() if len(tests) == 0]

    def get_impacted_tests(self, modified_files: List[str]) -> List[str]:
        """
        Determines which test files should be run based on modified source files.
        Uses cross-stack blast radius to identify downstream callers and route mappings.
        """
        impacted_tests: Set[str] = set()
        norm_modified = [f.replace("\\", "/") for f in modified_files]
        all_tests = self.discover_tests()

        # 1. If test file itself was modified, include it directly
        for f in norm_modified:
            for tf in all_tests:
                if f == tf or f.endswith(tf) or tf.endswith(f):
                    impacted_tests.add(tf)

        route_map = self.map_tests_to_routes()

        # 2. Check blast radius for modified files
        for mod_f in norm_modified:
            blast = self.graph.get_blast_radius(mod_f)
            affected_nodes = set(blast.get("affected_nodes", []))
            affected_nodes.add(blast.get("target", mod_f))

            for node_id in affected_nodes:
                if node_id in route_map:
                    for tf in route_map[node_id]:
                        impacted_tests.add(tf)

            # Also check if mod_f matches any route file directly
            for route_id, tests in route_map.items():
                if mod_f in route_id:
                    for tf in tests:
                        impacted_tests.add(tf)

        return sorted(list(impacted_tests))

    def generate_impact_report(self, modified_files: List[str]) -> Dict[str, Any]:
        """Generates a comprehensive test impact summary report."""
        mapping = self.map_tests_to_routes()
        untested = self.get_untested_routes()
        impacted = self.get_impacted_tests(modified_files)
        total_routes = len(mapping)
        tested_count = total_routes - len(untested)

        coverage_ratio = (tested_count / total_routes) if total_routes > 0 else 1.0

        return {
            "modified_files": modified_files,
            "impacted_tests": impacted,
            "untested_routes": untested,
            "total_routes": total_routes,
            "tested_routes_count": tested_count,
            "coverage_ratio": round(coverage_ratio, 3),
            "route_to_tests_map": mapping,
        }
