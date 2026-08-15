"""Parser for extracting FastAPI route decorators, handlers, and parameter models using Tree-sitter."""

import re

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from stackbridge.core.models import (
    BackendRoute,
    EndpointParam,
    FastAPIRoute,
    HttpMethod,
)


class PythonRouteParser:
    """Extracts FastAPI route handlers and request/response models from Python AST."""

    def __init__(self) -> None:
        self.py_lang = Language(tspython.language())
        self.parser = Parser(self.py_lang)

    def _extract_router_prefixes(self, root_node: Node, source_bytes: bytes) -> dict[str, str]:
        """Extracts router variables and prefixes, e.g. router = APIRouter(prefix='/api/v1')."""
        prefixes: dict[str, str] = {}

        def traverse(node: Node) -> None:
            if node.type == "assignment":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left and right and right.type == "call":
                    func = right.child_by_field_name("function")
                    if func and func.text == b"APIRouter":
                        var_name = source_bytes[left.start_byte:left.end_byte].decode("utf-8").strip()
                        args = right.child_by_field_name("arguments")
                        if args:
                            for arg in args.children:
                                if arg.type == "keyword_argument":
                                    k_name = arg.child_by_field_name("name")
                                    k_value = arg.child_by_field_name("value")
                                    if k_name and k_value and k_name.text == b"prefix":
                                        prefix_val = source_bytes[k_value.start_byte:k_value.end_byte].decode("utf-8").strip("'\"")
                                        prefixes[var_name] = prefix_val

            for child in node.children:
                traverse(child)

        traverse(root_node)
        return prefixes

    def _parse_route_decorator(
        self, decorator_node: Node, source_bytes: bytes, prefixes: dict[str, str]
    ) -> tuple[str, str, HttpMethod, str | None] | None:
        """Parses @router.get("/path", response_model=...) decorator."""
        dec_text = source_bytes[decorator_node.start_byte:decorator_node.end_byte].decode("utf-8")
        
        match = re.search(r"@([a-zA-Z0-9_]+)\.(get|post|put|delete|patch|options|head)\s*\((.*)\)", dec_text, re.DOTALL)
        if not match:
            return None
        
        router_var, method_name, args_str = match.groups()
        http_method = HttpMethod(method_name.upper())
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

    def _extract_orm_references_from_func(self, func_node: Node, source_bytes: bytes) -> list[str]:
        """Extracts referenced ORM models (e.g. db.query(BillingAccount), select(User)) from function node."""
        refs: set[str] = set()
        
        def traverse(node: Node) -> None:
            if node.type == "call":
                func = node.child_by_field_name("function")
                if func:
                    func_text = source_bytes[func.start_byte:func.end_byte].decode("utf-8")
                    if func_text.endswith(".query") or func_text == "select":
                        args = node.child_by_field_name("arguments")
                        if args:
                            for arg in args.children:
                                if arg.type == "identifier":
                                    id_name = source_bytes[arg.start_byte:arg.end_byte].decode("utf-8")
                                    refs.add(id_name)
            for child in node.children:
                traverse(child)

        traverse(func_node)
        return sorted(list(refs))

    def parse_code(self, source_code: str, file_path: str = "routes.py") -> list[BackendRoute]:
        """Parses Python source code string and returns detected FastAPI routes."""
        source_bytes = source_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        prefixes = self._extract_router_prefixes(tree.root_node, source_bytes)

        routes: list[BackendRoute] = []

        def traverse(node: Node) -> None:
            if node.type == "decorated_definition":
                line_number = node.start_point.row + 1
                func_node = None
                decorator_nodes: list[Node] = []

                for child in node.children:
                    if child.type == "decorator":
                        decorator_nodes.append(child)
                    elif child.type in ("function_definition", "async_function_definition"):
                        func_node = child

                if func_node and decorator_nodes:
                    func_name_node = func_node.child_by_field_name("name")
                    func_name = (
                        source_bytes[func_name_node.start_byte:func_name_node.end_byte].decode("utf-8")
                        if func_name_node
                        else "unknown"
                    )

                    orm_refs = self._extract_orm_references_from_func(func_node, source_bytes)

                    for dec_node in decorator_nodes:
                        parsed_dec = self._parse_route_decorator(dec_node, source_bytes, prefixes)
                        if parsed_dec:
                            raw_subpath, full_path, http_method, resp_model = parsed_dec
                            
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

            for child in node.children:
                traverse(child)

        traverse(tree.root_node)
        return routes

    def parse_file(self, file_path: str) -> list[BackendRoute]:
        """Parses a Python route file and returns detected FastAPI backend routes."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_code(content, file_path=file_path)


# Compatibility standalone functions

def _normalize_fastapi_path_to_regex(path: str) -> tuple[str, list[str]]:
    cleaned = path.rstrip("/") if len(path) > 1 else path
    path_params: list[str] = []
    
    def replace_param(match: re.Match) -> str:
        param_name = match.group(1)
        path_params.append(param_name)
        return '[^/]+'
    
    pattern = re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}', replace_param, cleaned)
    regex = f"^{pattern}$"
    return regex, path_params


def _extract_decorator_info(decorator_node: Node, source_code: bytes) -> tuple[str, str, str] | None:
    if not decorator_node.text:
        return None
    decorator_text = decorator_node.text.decode('utf-8')
    http_methods = ['get', 'post', 'put', 'delete', 'patch', 'options', 'head']
    pattern = r'@(?:app|router)\.(\w+)\s*\(\s*["\']([^"\']+)["\']'
    match = re.search(pattern, decorator_text)
    if match:
        method = match.group(1).lower()
        path = match.group(2)
        if method in http_methods:
            return (method.upper(), path, decorator_text)
    return None


def _find_function_definition(decorator_node: Node) -> Node | None:
    parent = decorator_node.parent
    if not parent:
        return None
    if parent.type == 'decorated_definition':
        for child in parent.children:
            if child.type in ('function_definition', 'async_function_definition'):
                return child
    return None


def extract_fastapi_routes(code: str, file_path: str) -> list[FastAPIRoute]:
    """Extract FastAPI route definitions from Python code using Tree-sitter."""
    parser_obj = PythonRouteParser()
    backend_routes = parser_obj.parse_code(code, file_path=file_path)
    fastapi_routes: list[FastAPIRoute] = []
    for r in backend_routes:
        reg, pparams = _normalize_fastapi_path_to_regex(r.normalized_path)
        method_str = r.http_methods[0].value if r.http_methods else "GET"
        fastapi_routes.append(
            FastAPIRoute(
                file_path=r.file_path,
                line=r.line_number,
                http_method=method_str,
                route_path=r.normalized_path,
                normalized_regex=reg,
                handler_name=r.function_name,
                path_params=[p.name for p in r.path_params],
            )
        )
    return fastapi_routes
