"""Parser for extracting FastAPI route decorators, handlers, and parameter models using Tree-sitter."""

import os
import re
from typing import Dict, Generator, List, Optional, Set, Tuple
from tree_sitter import Language, Node, Parser
import tree_sitter_python as tspython

from stackbridge.core.models import BackendRoute, EndpointParam, FastAPIRoute, HttpMethod


def _walk_ast(root_node: Node) -> Generator[Node, None, None]:
    """Memory-safe, zero-allocation TreeCursor traversal across tree-sitter ASTs."""
    cursor = root_node.walk()
    visited_children = False
    while True:
        if not visited_children:
            yield cursor.node
            if cursor.goto_first_child():
                continue
        visited_children = False
        if cursor.goto_next_sibling():
            continue
        if cursor.goto_parent():
            visited_children = True
            continue
        break


class PythonRouteParser:
    """Extracts FastAPI route handlers and request/response models from Python AST."""

    _py_lang = Language(tspython.language())

    def __init__(self) -> None:
        pass

    @property
    def parser(self) -> Parser:
        return Parser(Language(tspython.language()))

    @staticmethod
    def resolve_subrouter_prefix(base_prefix: str, sub_path: str) -> str:
        """Concatenates router base prefix and endpoint sub-path ensuring normalized slashes."""
        clean_prefix = "/" + base_prefix.strip("/") if base_prefix and base_prefix.strip("/") else ""
        clean_subpath = "/" + sub_path.strip("/") if sub_path and sub_path.strip("/") else ""
        full_path = f"{clean_prefix}{clean_subpath}"
        return full_path if full_path else "/"

    def _extract_router_prefixes(self, root_node: Optional[Node], source_bytes: bytes) -> Dict[str, str]:
        """Extracts router variables and prefixes, e.g. router = APIRouter(prefix='/api/v1') and include_router."""
        source_str = source_bytes.decode("utf-8", errors="replace")
        own_prefixes: Dict[str, str] = {}
        includes: List[Tuple[str, str, str]] = []

        # 1. Router assignments
        for match in re.finditer(r"(\w+)\s*=\s*(?:APIRouter|FastAPI)\s*\((.*?)\)", source_str, re.DOTALL):
            var_name, args_str = match.groups()
            prefix_match = re.search(r"""prefix\s*=\s*["']([^"']+)["']""", args_str)
            prefix_val = prefix_match.group(1).strip() if prefix_match else ""
            own_prefixes[var_name] = prefix_val

        # 2. include_router calls
        for match in re.finditer(r"(\w+)\.include_router\s*\(\s*(\w+)(?:[^,)]*prefix\s*=\s*['\"]([^'\"]+)['\"])?", source_str):
            parent_var = match.group(1).strip()
            target_var = match.group(2).strip()
            inc_prefix = match.group(3).strip() if match.group(3) else ""
            includes.append((parent_var, target_var, inc_prefix))

        # Compute accumulated prefixes idempotently
        accumulated: Dict[str, str] = dict(own_prefixes)
        for _ in range(len(includes) + 1):
            for parent_var, target_var, inc_prefix in includes:
                parent_p = accumulated.get(parent_var, "")
                target_own = own_prefixes.get(target_var, "")
                combined = self.resolve_subrouter_prefix(parent_p, self.resolve_subrouter_prefix(inc_prefix, target_own))
                if combined and combined != "/":
                    accumulated[target_var] = combined

        return accumulated

    def _extract_imports_and_includes(self, root_node: Node, source_bytes: bytes) -> Tuple[Dict[str, str], List[Tuple[str, str, str]]]:
        """Extracts imported symbols and include_router calls."""
        source_str = source_bytes.decode("utf-8", errors="replace")
        imports: Dict[str, str] = {}
        includes: List[Tuple[str, str, str]] = []

        # 1. Extract import statements
        for match in re.finditer(r"from\s+([\w\.]+)\s+import\s+([^\n#]+)", source_str):
            mod = match.group(1).strip()
            syms = match.group(2).strip()
            for sym in syms.split(","):
                clean = sym.strip()
                if " as " in clean:
                    alias = clean.split(" as ")[-1].strip()
                    if alias:
                        imports[alias] = mod
                elif clean:
                    imports[clean] = mod

        # 2. Extract include_router calls
        for match in re.finditer(r"(\w+)\.include_router\s*\(\s*(\w+)(?:[^,)]*prefix\s*=\s*['\"]([^'\"]+)['\"])?", source_str):
            parent_var = match.group(1).strip()
            target_var = match.group(2).strip()
            inc_prefix = match.group(3).strip() if match.group(3) else ""
            includes.append((parent_var, target_var, inc_prefix))

        return imports, includes

    def _parse_route_decorator(
        self, decorator_node: Node, source_bytes: bytes, prefixes: Dict[str, str]
    ) -> Optional[Tuple[str, str, HttpMethod, Optional[str]]]:
        """Parses FastAPI route decorators (@router.get) and MCP tool decorators (@mcp.tool)."""
        dec_text = source_bytes[decorator_node.start_byte:decorator_node.end_byte].decode("utf-8", errors="replace")

        # 1. FastAPI decorator match
        match = re.search(r"@([a-zA-Z0-9_]+)\.(get|post|put|delete|patch|options|head)\s*\((.*)\)", dec_text, re.DOTALL)
        if match:
            router_var, method_name, args_str = match.groups()
            try:
                http_method = HttpMethod(method_name.upper())
            except ValueError:
                return None

            prefix = prefixes.get(router_var, "")

            path_match = re.search(r"""(?:path\s*=\s*)?["']([^"']+)["']""", args_str)
            if not path_match:
                return None

            raw_subpath = path_match.group(1)
            if prefix:
                clean_prefix = "/" + prefix.strip("/")
                clean_subpath = "/" + raw_subpath.strip("/") if raw_subpath.strip("/") else ""
                full_path = f"{clean_prefix}{clean_subpath}"
            else:
                full_path = "/" + raw_subpath.strip("/") if raw_subpath.strip("/") else "/"

            response_model = None
            rm_match = re.search(r"response_model\s*=\s*([a-zA-Z0-9_\[\],\s]+)", args_str)
            if rm_match:
                response_model = rm_match.group(1).strip()

            return raw_subpath, full_path, http_method, response_model

        # 2. MCP Server Tool / Resource match (@mcp.tool(), @mcp.resource(), @server.tool(), @server.call_tool())
        mcp_match = re.search(r"@([a-zA-Z0-9_]+)\.(tool|resource|call_tool)(?:\s*\((.*?)\)|\s*)", dec_text, re.DOTALL)
        if mcp_match:
            server_var, tool_type, mcp_args = mcp_match.groups()
            mcp_method = HttpMethod.MCP_RESOURCE if tool_type == "resource" else HttpMethod.MCP_TOOL
            custom_name = None
            if mcp_args:
                name_match = re.search(r"""(?:name\s*=\s*)?["']([^"']+)["']""", mcp_args)
                if name_match:
                    custom_name = name_match.group(1)

            return "", custom_name or "", mcp_method, None

        return None

    def _extract_docstring_from_func(self, func_node: Node, source_bytes: bytes) -> Optional[str]:
        """Extracts docstring contract from function definition node."""
        body = func_node.child_by_field_name("body")
        if body and len(body.children) > 0:
            for child in body.children:
                if child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "string":
                            raw = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="replace")
                            clean = raw.strip("'''\"\"\"\n\r ").strip()
                            return clean
                elif child.type not in ("comment",):
                    break
        return None

    def _extract_orm_references_from_func(self, func_node: Node, source_bytes: bytes) -> List[str]:
        """Extracts referenced ORM models (e.g. db.query(BillingAccount), select(User)) from function node."""
        refs: Set[str] = set()

        body = func_node.child_by_field_name("body")
        if not body:
            return []

        func_text = source_bytes[body.start_byte:body.end_byte].decode("utf-8", errors="replace")
        query_matches = re.findall(r"(?:query|select)\s*\(\s*([a-zA-Z0-9_]+)", func_text)
        for q in query_matches:
            if q and q not in ("db", "session", "select", "query"):
                refs.add(q)

        return sorted(list(refs))

    def _extract_routes_from_tree(
        self, root_node: Node, source_bytes: bytes, prefixes: Dict[str, str], file_path: str = "routes.py"
    ) -> List[BackendRoute]:
        """Extracts FastAPI routes and MCP server tools directly from an already parsed tree-sitter AST root node."""
        routes: List[BackendRoute] = []

        for node in root_node.children:
            if node.type == "decorated_definition":
                line_number = node.start_point.row + 1
                func_node = None
                decorator_nodes: List[Node] = []

                for child in node.children:
                    if child.type == "decorator":
                        decorator_nodes.append(child)
                    elif child.type in ("function_definition", "async_function_definition"):
                        func_node = child

                if func_node and decorator_nodes:
                    parsed_route_decs = []
                    for dec_node in decorator_nodes:
                        parsed_dec = self._parse_route_decorator(dec_node, source_bytes, prefixes)
                        if parsed_dec:
                            parsed_route_decs.append(parsed_dec)

                    if parsed_route_decs:
                        func_name_node = func_node.child_by_field_name("name")
                        func_name = (
                            source_bytes[func_name_node.start_byte:func_name_node.end_byte].decode("utf-8", errors="replace")
                            if func_name_node
                            else "unknown"
                        )
                        orm_refs = self._extract_orm_references_from_func(func_node, source_bytes)
                        docstring = self._extract_docstring_from_func(func_node, source_bytes)

                        for raw_subpath, full_path, http_method, resp_model in parsed_route_decs:
                            if http_method in (HttpMethod.MCP_TOOL, HttpMethod.MCP_RESOURCE):
                                tool_name = full_path if full_path else func_name
                                tool_path = f"tools/{tool_name}"
                                routes.append(
                                    BackendRoute(
                                        file_path=file_path,
                                        line_number=line_number,
                                        function_name=func_name,
                                        raw_path=tool_path,
                                        normalized_path=tool_path,
                                        http_methods=[http_method],
                                        path_params=[],
                                        query_params=[],
                                        request_model=None,
                                        response_model=docstring or resp_model,
                                        orm_models_referenced=orm_refs,
                                    )
                                )
                            else:
                                param_names = re.findall(r"\{([a-zA-Z0-9_]+)(?::[^}]+)?\}", full_path)
                                path_params = [
                                    EndpointParam(name=p, param_type="path", required=True)
                                    for p in param_names
                                ]

                                routes.append(
                                    BackendRoute(
                                        file_path=file_path,
                                        line_number=line_number,
                                        function_name=func_name,
                                        raw_path=full_path,
                                        normalized_path=full_path,
                                        http_methods=[http_method],
                                        path_params=path_params,
                                        response_model=resp_model,
                                        orm_models_referenced=orm_refs,
                                    )
                                )

        return routes

    def parse_code(self, source_code: str, file_path: str = "routes.py") -> List[BackendRoute]:
        """Parses Python source code string and returns detected FastAPI routes."""
        source_bytes = source_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        prefixes = self._extract_router_prefixes(tree.root_node, source_bytes)
        return self._extract_routes_from_tree(tree.root_node, source_bytes, prefixes, file_path=file_path)

    def parse_file(self, file_path: str) -> List[BackendRoute]:
        """Parses a Python route file and returns detected FastAPI backend routes."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_code(content, file_path=file_path)


# Compatibility standalone functions

def extract_fastapi_routes(code: str, file_path: str) -> List[FastAPIRoute]:
    """Extracts route endpoints from Python FastAPI source code string."""
    parser_obj = PythonRouteParser()
    backend_routes = parser_obj.parse_code(code, file_path=file_path)
    routes: List[FastAPIRoute] = []
    for br in backend_routes:
        methods = [m.value if isinstance(m, HttpMethod) else str(m) for m in br.http_methods]
        primary_method = methods[0] if methods else "GET"
        routes.append(
            FastAPIRoute(
                file_path=br.file_path,
                line=br.line_number,
                function_name=br.function_name,
                endpoint_path=br.raw_path,
                http_method=primary_method,
                response_model=br.response_model,
                models_accessed=br.orm_models_referenced,
            )
        )
    return routes
