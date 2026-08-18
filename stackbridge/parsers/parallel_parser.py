"""Parallel AST Parser for TypeScript/TSX, FastAPI routes, and SQLAlchemy models."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from stackbridge.core.models import BackendRoute, FrontendEndpointCall, ORMModel
from stackbridge.parsers.py_route_parser import PythonRouteParser
from stackbridge.parsers.sqlalchemy_parser import SQLAlchemyParser
from stackbridge.parsers.ts_fetch_parser import TypeScriptFetchParser


class ParallelASTParser:
    """Multi-threaded AST parser that concurrently scans and extracts fullstack AST definitions."""

    _init_lock = threading.Lock()

    def __init__(self, max_workers: Optional[int] = None) -> None:
        self.max_workers = max_workers or min(32, (os.cpu_count() or 4) + 4)
        self._thread_local = threading.local()

    def _get_parsers(self) -> Tuple[TypeScriptFetchParser, PythonRouteParser, SQLAlchemyParser]:
        if not hasattr(self._thread_local, "parsers"):
            with self._init_lock:
                self._thread_local.parsers = (
                    TypeScriptFetchParser(),
                    PythonRouteParser(),
                    SQLAlchemyParser(),
                )
        return self._thread_local.parsers

    def parse_single_file(self, full_file_path: str, rel_file_path: Optional[str] = None) -> Dict[str, Any]:
        """Parses a single file for frontend calls, backend routes, and ORM models, returning AST data and SHA-256."""
        rel_path = (rel_file_path or os.path.basename(full_file_path)).replace("\\", "/")
        ts_parser, py_route_parser, sql_parser = self._get_parsers()

        with open(full_file_path, "rb") as f:
            content_bytes = f.read()
        sha256 = hashlib.sha256(content_bytes).hexdigest()

        ext = os.path.splitext(full_file_path)[1].lower()

        fe_calls: List[FrontendEndpointCall] = []
        routes: List[BackendRoute] = []
        models: List[ORMModel] = []
        py_data: Dict[str, Any] = {}

        if ext in (".ts", ".tsx", ".js", ".jsx"):
            try:
                calls = ts_parser.parse_file(full_file_path)
                for c in calls:
                    c.file_path = rel_path
                fe_calls = calls
            except Exception:
                pass

        elif ext == ".py":
            try:
                content_str = content_bytes.decode("utf-8", errors="replace")
                prefixes = py_route_parser._extract_router_prefixes(None, content_bytes)
                imports, includes = py_route_parser._extract_imports_and_includes(None, content_bytes)
                routes = py_route_parser.parse_code(content_str, file_path=rel_path)
                models = sql_parser.parse_code(content_str, file_path=rel_path)
                py_data = {
                    "prefixes": prefixes,
                    "imports": imports,
                    "includes": includes,
                }
            except Exception:
                pass

        return {
            "rel_path": rel_path,
            "full_path": str(Path(full_file_path).resolve()),
            "sha256": sha256,
            "fe_calls": fe_calls,
            "routes": routes,
            "models": models,
            "py_data": py_data,
        }

    def parse_files(
        self,
        file_inputs: Union[List[str], List[Tuple[str, str]]],
        max_workers: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Concurrently parses a list of file paths or (full_path, rel_path) tuples."""
        workers = max_workers or self.max_workers
        normalized_inputs: List[Tuple[str, str]] = []

        for item in file_inputs:
            if isinstance(item, tuple):
                normalized_inputs.append((str(item[0]), str(item[1])))
            else:
                normalized_inputs.append((str(item), os.path.basename(str(item))))

        if not normalized_inputs:
            return []

        results: List[Dict[str, Any]] = []
        for full_p, rel_p in normalized_inputs:
            try:
                res = self.parse_single_file(full_p, rel_p)
                results.append(res)
            except Exception:
                pass

        # Sort for deterministic ordering
        results.sort(key=lambda r: r["rel_path"])
        return results
