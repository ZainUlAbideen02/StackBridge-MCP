"""Parser for extracting FastAPI route decorators, handlers, and parameter models."""

import re
from typing import List, Tuple, Optional
from tree_sitter import Parser, Language, Node
from tree_sitter_python import language as python_language

from stackbridge.core.models import FastAPIRoute


def extract_fastapi_routes(code: str, file_path: str) -> List[FastAPIRoute]:
    """
    Extract FastAPI route definitions from Python code using Tree-sitter.
    
    Args:
        code: The source code as a string
        file_path: Path to the file being parsed
        
    Returns:
        List of FastAPIRoute objects representing detected routes
    """
    lang = Language(python_language())
    parser = Parser(lang)
    tree = parser.parse(code.encode('utf-8'))
    root_node = tree.root_node
    
    routes: List[FastAPIRoute] = []
    
    # Query for decorated_definition with decorator
    query_string = """
        (decorated_definition
            (decorator) @decorator
        )
    """
    
    query = lang.query(query_string)
    captures_dict = query.captures(root_node)
    
    decorator_nodes = captures_dict.get('decorator', [])
    
    for node in decorator_nodes:
        decorator_info = _extract_decorator_info(node, code.encode('utf-8'))
        if not decorator_info:
            continue
        
        http_method, route_path, _ = decorator_info
        
        # Find the associated function definition
        func_node = _find_function_definition(node)
        if not func_node:
            continue
        
        # Extract function name
        func_name_node = func_node.child_by_field_name('name')
        if not func_name_node:
            continue
        
        handler_name = func_name_node.text.decode('utf-8')
        
        # Get line number (tree-sitter uses 0-indexed rows)
        line_number = node.start_point[0] + 1
        
        # Normalize the path to regex and extract params
        normalized_regex, path_params = _normalize_fastapi_path_to_regex(route_path)
        
        route = FastAPIRoute(
            file_path=file_path,
            line=line_number,
            http_method=http_method,
            route_path=route_path,
            normalized_regex=normalized_regex,
            handler_name=handler_name,
            path_params=path_params
        )
        routes.append(route)
    
    return routes


def _normalize_fastapi_path_to_regex(path: str) -> Tuple[str, List[str]]:
    """
    Convert FastAPI path format to regex pattern and extract path parameters.
    
    Args:
        path: The raw FastAPI route path (e.g., "/users/{user_id:int}/posts")
        
    Returns:
        Tuple of (regex_pattern, list of param names)
    """
    # Strip trailing slash except if path is just "/"
    cleaned = path.rstrip("/") if len(path) > 1 else path
    
    path_params: List[str] = []
    
    def replace_param(match: re.Match) -> str:
        param_name = match.group(1)
        path_params.append(param_name)
        # Replace with wildcard that matches non-slash characters
        return '[^/]+'
    
    # Match {param} or {param:type} patterns
    pattern = re.sub(r'\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}', replace_param, cleaned)
    
    # Anchor the regex
    regex = f"^{pattern}$"
    return regex, path_params


def _extract_decorator_info(decorator_node: Node, source_code: bytes) -> Optional[Tuple[str, str, str]]:
    """
    Extract HTTP method and path from a FastAPI decorator.
    
    Args:
        decorator_node: The decorator AST node
        source_code: The source code as bytes
        
    Returns:
        Tuple of (http_method, route_path, decorator_text) or None if not a valid route decorator
    """
    # Get the full decorator text
    decorator_text = decorator_node.text.decode('utf-8')
    
    # Check if this is an @app or @router decorator with HTTP method
    # Patterns: @app.get, @app.post, @router.get, @router.post, etc.
    http_methods = ['get', 'post', 'put', 'delete', 'patch', 'options', 'head']
    
    # Match patterns like @app.get("/path") or @router.delete("/path")
    pattern = r'@(?:app|router)\.(\w+)\s*\(\s*["\']([^"\']+)["\']'
    match = re.search(pattern, decorator_text)
    
    if match:
        method = match.group(1).lower()
        path = match.group(2)
        if method in http_methods:
            return (method.upper(), path, decorator_text)
    
    return None


def _find_function_definition(decorator_node: Node) -> Optional[Node]:
    """Find the function definition that follows a decorator."""
    # Navigate to the decorated function
    parent = decorator_node.parent
    if not parent:
        return None
    
    # In Python AST, the decorated_definition contains both decorator and function
    if parent.type == 'decorated_definition':
        for child in parent.children:
            if child.type == 'function_definition':
                return child
    
    return None
