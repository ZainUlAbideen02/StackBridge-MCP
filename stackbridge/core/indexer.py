"""High-scale incremental repository indexer with two-tier mtime/SHA-256 caching and ignore rules."""

import fnmatch
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

try:
    import pathspec
    HAS_PATHSPEC = True
except (ImportError, ModuleNotFoundError):
    pathspec = None
    HAS_PATHSPEC = False

from stackbridge.core.graph import StackGraph
from stackbridge.core.models import (
    BackendRoute,
    EndpointParam,
    FrontendEndpointCall,
    HttpMethod,
    ORMField,
    ORMModel,
)
from stackbridge.core.route_matcher import match_frontend_call_to_routes
from stackbridge.parsers.py_route_parser import PythonRouteParser


DEFAULT_IGNORE_PATTERNS: List[str] = [
    ".git",
    ".git/**",
    "node_modules",
    "node_modules/**",
    ".venv",
    ".venv/**",
    "venv",
    "venv/**",
    "env",
    "env/**",
    "__pycache__",
    "__pycache__/**",
    ".pytest_cache",
    ".pytest_cache/**",
    ".mypy_cache",
    ".mypy_cache/**",
    ".stackbridge",
    ".stackbridge/**",
    ".gemini",
    ".gemini/**",
    "coverage",
    "coverage/**",
    "htmlcov",
    "htmlcov/**",
    "dist",
    "dist/**",
    "build",
    "build/**",
    ".next",
    ".next/**",
    ".turbo",
    ".turbo/**",
    ".idea",
    ".idea/**",
    ".vscode",
    ".vscode/**",
    "tests/test_*.py",
    "**/test_*.py",
    "scripts/*",
    "scripts/**",
]


class IndexReport:
    """Statistics summary for an indexing execution."""

    def __init__(
        self,
        total_files: int,
        modified_files: int,
        cached_files_hit: int,
        duration_ms: float,
        graph: StackGraph,
    ) -> None:
        self.total_files = total_files
        self.modified_files = modified_files
        self.cached_files_hit = cached_files_hit
        self.duration_ms = duration_ms
        self.graph = graph

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "modified_files": self.modified_files,
            "cached_files_hit": self.cached_files_hit,
            "duration_ms": round(self.duration_ms, 2),
            "node_count": self.graph.node_count,
            "edge_count": self.graph.edge_count,
        }


class IncrementalIndexer:
    """Incremental full-stack AST indexer using two-tier (mtime/size -> SHA-256) caching and parallel AST parsing."""

    def __init__(
        self,
        repo_path: Union[str, Path],
        cache_path: Optional[Union[str, Path]] = None,
        ignore_patterns: Optional[List[str]] = None,
        max_workers: Optional[int] = None,
    ) -> None:
        self.repo_dir = Path(repo_path).resolve()
        self.cache_file = Path(cache_path).resolve() if cache_path else self.repo_dir / ".stackbridge" / "cache.json"
        self.ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
        if ignore_patterns:
            self.ignore_patterns.extend(ignore_patterns)

        self._pathspec_matcher = None
        self._load_gitignore_patterns()
        from stackbridge.parsers.parallel_parser import ParallelASTParser

        self.parallel_parser = ParallelASTParser(max_workers=max_workers)

    def _load_gitignore_patterns(self) -> None:
        """Discovers and parses root and nested .gitignore files in the repository."""
        collected_lines: List[str] = list(self.ignore_patterns)

        for root, dirs, files in os.walk(self.repo_dir):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in (
                    ".git",
                    "node_modules",
                    ".venv",
                    "venv",
                    "env",
                    "__pycache__",
                    ".pytest_cache",
                    ".stackbridge",
                    ".gemini",
                    ".idea",
                    ".vscode",
                    ".mypy_cache",
                    "coverage",
                    "htmlcov",
                    "dist",
                    "build",
                    ".next",
                    ".turbo",
                )
            ]
            if ".gitignore" in files:
                git_path = Path(root) / ".gitignore"
                rel_root = os.path.relpath(root, self.repo_dir).replace("\\", "/")
                try:
                    with open(git_path, "r", encoding="utf-8") as f:
                        for line in f:
                            clean = line.strip()
                            if clean and not clean.startswith("#"):
                                if rel_root != ".":
                                    prefix = rel_root.strip("/")
                                    collected_lines.append(f"{prefix}/{clean}")
                                    collected_lines.append(f"{prefix}/{clean}/**")
                                else:
                                    collected_lines.append(clean)
                                    collected_lines.append(f"{clean}/**")
                                    collected_lines.append(f"**/{clean}/**")
                                    collected_lines.append(f"**/{clean}")
                except Exception:
                    pass

        self.ignore_patterns = collected_lines

        if HAS_PATHSPEC and pathspec:
            try:
                self._pathspec_matcher = pathspec.PathSpec.from_lines("gitwildmatch", self.ignore_patterns)
            except Exception:
                self._pathspec_matcher = None

    def should_ignore(self, rel_path: str) -> bool:
        """Checks if a relative path matches default or .gitignore exclusion rules using pathspec or fallback."""
        norm_path = rel_path.replace("\\", "/").strip("/")
        parts = norm_path.split("/")

        # Fast direct check for common directory names
        for part in parts:
            if part in (
                ".git",
                "node_modules",
                ".venv",
                "venv",
                "env",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".stackbridge",
                ".gemini",
                "coverage",
                "htmlcov",
                "dist",
                "build",
                ".next",
                ".turbo",
                ".idea",
                ".vscode",
            ):
                return True

        if self._pathspec_matcher:
            try:
                if self._pathspec_matcher.match_file(norm_path):
                    return True
            except Exception:
                pass

        # Robust standard fallback
        for pat in self.ignore_patterns:
            pat_clean = pat.strip("/").replace("/**", "/*")
            if fnmatch.fnmatch(norm_path, pat_clean) or fnmatch.fnmatch(norm_path, f"*/{pat_clean}") or fnmatch.fnmatch(norm_path, f"**/{pat_clean}"):
                return True
            if any(fnmatch.fnmatch(p, pat_clean) for p in parts):
                return True

        return False

    def discover_files(self) -> List[Tuple[str, str]]:
        """Finds all candidate TypeScript and Python files in repository respecting ignore rules."""
        candidate_files: List[Tuple[str, str]] = []

        for root, dirs, files in os.walk(self.repo_dir):
            rel_root = os.path.relpath(root, self.repo_dir).replace("\\", "/")
            if rel_root != ".":
                if self.should_ignore(rel_root):
                    dirs[:] = []
                    continue

            dirs[:] = [d for d in dirs if not self.should_ignore(f"{rel_root}/{d}" if rel_root != "." else d)]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, self.repo_dir).replace("\\", "/")
                    if not self.should_ignore(rel_p):
                        candidate_files.append((full_p, rel_p))

        candidate_files.sort(key=lambda x: x[1])
        return candidate_files

    def _load_cache(self) -> Dict[str, Any]:
        """Loads cached file entries from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("files", {})
            except Exception:
                return {}
        return {}

    def _save_cache(self, files_cache: Dict[str, Any]) -> None:
        """Persists file AST cache to disk."""
        try:
            if not self.cache_file.parent.exists():
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0.0", "files": files_cache}, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _compute_sha256(file_path: str) -> str:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    @staticmethod
    def _serialize_fe_call(call: FrontendEndpointCall) -> Dict[str, Any]:
        return {
            "file_path": call.file_path,
            "line_number": call.line_number,
            "raw_url": call.raw_url,
            "normalized_path": call.normalized_path,
            "http_method": call.http_method.value if isinstance(call.http_method, HttpMethod) else str(call.http_method),
            "path_params": call.path_params,
            "query_params": call.query_params,
            "is_template": call.is_template,
            "body_type": call.body_type,
        }

    @staticmethod
    def _deserialize_fe_call(d: Dict[str, Any]) -> FrontendEndpointCall:
        method_str = d.get("http_method", "GET")
        try:
            method_enum = HttpMethod(method_str)
        except Exception:
            method_enum = HttpMethod.GET
        return FrontendEndpointCall(
            file_path=d.get("file_path", ""),
            line_number=d.get("line_number", 1),
            raw_url=d.get("raw_url", ""),
            normalized_path=d.get("normalized_path", ""),
            http_method=method_enum,
            path_params=d.get("path_params", []),
            query_params=d.get("query_params", []),
            is_template=d.get("is_template", False),
            body_type=d.get("body_type"),
        )

    @staticmethod
    def _serialize_route(r: BackendRoute) -> Dict[str, Any]:
        return {
            "file_path": r.file_path,
            "line_number": r.line_number,
            "function_name": r.function_name,
            "raw_path": r.raw_path,
            "normalized_path": r.normalized_path,
            "http_methods": [m.value if isinstance(m, HttpMethod) else str(m) for m in r.http_methods],
            "path_params": [
                {
                    "name": p.name,
                    "param_type": p.param_type,
                    "required": p.required,
                    "schema_type": p.schema_type,
                }
                for p in r.path_params
            ],
            "query_params": [
                {
                    "name": p.name,
                    "param_type": p.param_type,
                    "required": p.required,
                    "schema_type": p.schema_type,
                }
                for p in r.query_params
            ],
            "request_model": r.request_model,
            "response_model": r.response_model,
            "orm_models_referenced": r.orm_models_referenced,
        }

    @staticmethod
    def _deserialize_route(d: Dict[str, Any]) -> BackendRoute:
        methods = []
        for m in d.get("http_methods", ["GET"]):
            clean_m = str(m).strip("[]'\" ")
            try:
                methods.append(HttpMethod(clean_m))
            except Exception:
                try:
                    methods.append(HttpMethod(str(m)))
                except Exception:
                    methods.append(HttpMethod.GET)
        path_params = [
            EndpointParam(
                name=p["name"],
                param_type=p.get("param_type", "path"),
                required=p.get("required", True),
                schema_type=p.get("schema_type"),
            )
            for p in d.get("path_params", [])
        ]
        query_params = [
            EndpointParam(
                name=p["name"],
                param_type=p.get("param_type", "query"),
                required=p.get("required", True),
                schema_type=p.get("schema_type"),
            )
            for p in d.get("query_params", [])
        ]
        return BackendRoute(
            file_path=d.get("file_path", ""),
            line_number=d.get("line_number", 1),
            function_name=d.get("function_name", ""),
            raw_path=d.get("raw_path", ""),
            normalized_path=d.get("normalized_path", ""),
            http_methods=methods or [HttpMethod.GET],
            path_params=path_params,
            query_params=query_params,
            request_model=d.get("request_model"),
            response_model=d.get("response_model"),
            orm_models_referenced=d.get("orm_models_referenced", []),
        )

    @staticmethod
    def _serialize_model(m: ORMModel) -> Dict[str, Any]:
        return {
            "file_path": m.file_path,
            "line_number": m.line_number,
            "class_name": m.class_name,
            "table_name": m.table_name,
            "fields": [
                {
                    "name": f.name,
                    "data_type": f.data_type,
                    "is_primary_key": f.is_primary_key,
                    "is_nullable": f.is_nullable,
                    "foreign_key": f.foreign_key,
                }
                for f in m.fields
            ],
            "relationships": m.relationships,
        }

    @staticmethod
    def _deserialize_model(d: Dict[str, Any]) -> ORMModel:
        fields = [
            ORMField(
                name=f["name"],
                data_type=f.get("data_type", "String"),
                is_primary_key=f.get("is_primary_key", False),
                is_nullable=f.get("is_nullable", True),
                foreign_key=f.get("foreign_key"),
            )
            for f in d.get("fields", [])
        ]
        return ORMModel(
            file_path=d.get("file_path", ""),
            line_number=d.get("line_number", 1),
            class_name=d.get("class_name", ""),
            table_name=d.get("table_name"),
            fields=fields,
            relationships=d.get("relationships", []),
        )

    def index(self, use_cache: bool = True) -> Tuple[StackGraph, IndexReport]:
        """Executes full or incremental index with two-tier (mtime/size -> SHA-256) caching."""
        start_time = time.perf_counter()
        files_to_scan = self.discover_files()
        total_files = len(files_to_scan)

        cached_store = self._load_cache() if use_cache else {}
        new_cache: Dict[str, Any] = {}

        files_to_parse: List[Tuple[str, str]] = []
        parsed_entries: Dict[str, Dict[str, Any]] = {}
        cached_hits = 0

        for full_p, rel_p in files_to_scan:
            try:
                stat = os.stat(full_p)
                curr_mtime = float(stat.st_mtime)
                curr_size = int(stat.st_size)
            except Exception:
                continue

            # Tier 1: Check (mtime, size) match without disk hashing
            if use_cache and rel_p in cached_store:
                cached_entry = cached_store[rel_p]
                cached_mtime = cached_entry.get("mtime")
                cached_size = cached_entry.get("size")

                if cached_mtime is not None and cached_size is not None and cached_mtime == curr_mtime and cached_size == curr_size:
                    # Tier 1 Fast Hit: Skip SHA-256 computation
                    cached_hits += 1
                    new_cache[rel_p] = cached_entry
                    parsed_entries[rel_p] = {
                        "rel_path": rel_p,
                        "full_path": full_p,
                        "sha256": cached_entry.get("sha256", ""),
                        "fe_calls": [self._deserialize_fe_call(c) for c in cached_entry.get("fe_calls", [])],
                        "routes": [self._deserialize_route(r) for r in cached_entry.get("routes", [])],
                        "models": [self._deserialize_model(m) for m in cached_entry.get("models", [])],
                        "py_data": cached_entry.get("py_data", {}),
                    }
                    continue

                # Tier 2: Check SHA-256 hash
                try:
                    curr_sha = self._compute_sha256(full_p)
                except Exception:
                    curr_sha = ""

                if curr_sha and cached_entry.get("sha256") == curr_sha:
                    # Tier 2 Hit: Content is identical, update mtime/size
                    cached_hits += 1
                    updated_entry = dict(cached_entry)
                    updated_entry["mtime"] = curr_mtime
                    updated_entry["size"] = curr_size
                    new_cache[rel_p] = updated_entry
                    parsed_entries[rel_p] = {
                        "rel_path": rel_p,
                        "full_path": full_p,
                        "sha256": curr_sha,
                        "fe_calls": [self._deserialize_fe_call(c) for c in cached_entry.get("fe_calls", [])],
                        "routes": [self._deserialize_route(r) for r in cached_entry.get("routes", [])],
                        "models": [self._deserialize_model(m) for m in cached_entry.get("models", [])],
                        "py_data": cached_entry.get("py_data", {}),
                    }
                    continue

            files_to_parse.append((full_p, rel_p))

        # Parse modified / new files in parallel
        if files_to_parse:
            fresh_results = self.parallel_parser.parse_files(files_to_parse)
            for res in fresh_results:
                rel_p = res["rel_path"]
                full_p = res["full_path"]
                try:
                    st = os.stat(full_p)
                    res_mtime = float(st.st_mtime)
                    res_size = int(st.st_size)
                except Exception:
                    res_mtime = 0.0
                    res_size = 0

                parsed_entries[rel_p] = res
                new_cache[rel_p] = {
                    "mtime": res_mtime,
                    "size": res_size,
                    "sha256": res["sha256"],
                    "fe_calls": [self._serialize_fe_call(c) for c in res["fe_calls"]],
                    "routes": [self._serialize_route(r) for r in res["routes"]],
                    "models": [self._serialize_model(m) for m in res["models"]],
                    "py_data": res["py_data"],
                }

        # Save freshly indexed cache store to disk
        self._save_cache(new_cache)

        # Assemble Full-Stack Dependency Graph from AST entries
        graph = self._assemble_graph(parsed_entries)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        report = IndexReport(
            total_files=total_files,
            modified_files=len(files_to_parse),
            cached_files_hit=cached_hits,
            duration_ms=duration_ms,
            graph=graph,
        )
        return graph, report

    def _assemble_graph(self, parsed_entries: Dict[str, Dict[str, Any]]) -> StackGraph:
        """Constructs StackGraph, resolves subrouter prefixes, and builds cross-boundary edges."""
        sg = StackGraph()
        py_parser = PythonRouteParser()

        parsed_fe_calls: List[Tuple[str, FrontendEndpointCall]] = []
        parsed_routes: List[Tuple[str, BackendRoute]] = []
        parsed_models: List[Tuple[str, ORMModel]] = []

        # 1. Register frontend calls and models
        for rel_p, data in parsed_entries.items():
            for c in data.get("fe_calls", []):
                fe_id = sg.add_frontend_call(c)
                parsed_fe_calls.append((fe_id, c))

            for m in data.get("models", []):
                m_id = sg.add_orm_model(m)
                parsed_models.append((m_id, m))

        # 2. Resolve cross-file router prefixes
        file_base_prefixes: Dict[str, str] = {}
        for rel_p, data in parsed_entries.items():
            py_data = data.get("py_data", {})
            prefixes = py_data.get("prefixes", {})
            includes = py_data.get("includes", [])
            imports = py_data.get("imports", {})

            for parent_var, target_var, inc_prefix in includes:
                target_p = prefixes.get(target_var, "")
                if not target_p and inc_prefix:
                    target_p = inc_prefix

                if target_p:
                    imported_mod = imports.get(target_var, "")
                    if imported_mod:
                        mod_path_suffix = imported_mod.replace(".", "/")
                        for other_file in parsed_entries.keys():
                            if other_file.endswith(f"{mod_path_suffix}.py") or mod_path_suffix in other_file:
                                file_base_prefixes[other_file] = target_p

        # 3. Register backend routes with resolved prefixes
        for rel_p, data in parsed_entries.items():
            base_prefix = file_base_prefixes.get(rel_p, "")
            for r in data.get("routes", []):
                route_copy = BackendRoute(
                    file_path=r.file_path,
                    line_number=r.line_number,
                    function_name=r.function_name,
                    raw_path=r.raw_path,
                    normalized_path=r.normalized_path,
                    http_methods=r.http_methods,
                    path_params=r.path_params,
                    query_params=r.query_params,
                    request_model=r.request_model,
                    response_model=r.response_model,
                    orm_models_referenced=r.orm_models_referenced,
                )
                if base_prefix and not route_copy.raw_path.startswith(base_prefix):
                    route_copy.raw_path = py_parser.resolve_subrouter_prefix(base_prefix, route_copy.raw_path)
                    route_copy.normalized_path = py_parser.resolve_subrouter_prefix(base_prefix, route_copy.normalized_path)
                r_id = sg.add_backend_route(route_copy)
                parsed_routes.append((r_id, route_copy))

        # 4. Link Frontend -> Backend Routes
        all_backend_routes = [r for _, r in parsed_routes]
        route_to_id = {r.raw_path: r_id for r_id, r in parsed_routes}
        route_to_id.update({r.normalized_path: r_id for r_id, r in parsed_routes})
        route_func_to_id = {f"{r.file_path}::{r.function_name}": r_id for r_id, r in parsed_routes}

        for fe_id, fe_call in parsed_fe_calls:
            matches = match_frontend_call_to_routes(fe_call, all_backend_routes, min_confidence=0.5)
            for match in matches:
                target_route = match.backend_route
                r_id = route_func_to_id.get(f"{target_route.file_path}::{target_route.function_name}")
                if not r_id:
                    r_id = route_to_id.get(target_route.normalized_path)
                if r_id:
                    sg.link_frontend_to_route(
                        fe_node_id=fe_id,
                        route_node_id=r_id,
                        confidence=match.confidence,
                        is_exact=match.is_exact,
                        param_mappings=match.param_mappings,
                    )

        # 5. Link Backend Routes -> ORM Models
        model_name_to_id = {m.class_name: m_id for m_id, m in parsed_models}
        for r_id, route in parsed_routes:
            for model_name in route.orm_models_referenced:
                if model_name in model_name_to_id:
                    sg.link_route_to_model(r_id, model_name_to_id[model_name])

        # 6. Link ORM Models -> ORM Models
        for m_id, model in parsed_models:
            for target_rel in model.relationships:
                if target_rel in model_name_to_id:
                    sg.link_model_to_model(m_id, model_name_to_id[target_rel])

        return sg
