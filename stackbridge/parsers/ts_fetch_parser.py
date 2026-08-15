"""Parser for extracting fetch calls and HTTP client requests from TypeScript / TSX files."""

import re
from typing import List, Tuple
from tree_sitter import Parser, Language, Node
from tree_sitter_typescript import language_tsx

from stackbridge.core.models import FrontendFetchCall


def extract_nextjs_fetches(code: str, file_path: str) -> List[FrontendFetchCall]:
    """
    Extract fetch() calls from TypeScript/TSX code using Tree-sitter.
    
    Args:
        code: The source code as a string
        file_path: Path to the file being parsed
        
    Returns:
        List of FrontendFetchCall objects representing detected fetch calls
    """
    lang = Language(language_tsx())
    parser = Parser(lang)
    tree = parser.parse(code.encode('utf-8'))
    root_node = tree.root_node
    
    fetches: List[FrontendFetchCall] = []
    
    # Query for call_expression where function is 'fetch'
    # Matches: fetch(url), fetch(url, options)
    query_string = """
        (call_expression
            function: (identifier) @func_name
            arguments: (arguments) @args
        )
    """
    
    query = lang.query(query_string)
    captures_dict = query.captures(root_node)
    
    # captures_dict is a dict like {'func_name': [nodes...], 'args': [nodes...]}
    func_nodes = captures_dict.get('func_name', [])
    args_nodes = captures_dict.get('args', [])
    
    for i, node in enumerate(func_nodes):
        if node.text.decode('utf-8') != 'fetch':
            continue
        
        args_node = args_nodes[i] if i < len(args_nodes) else None
            
        if not args_node:
            continue
        
        # Get line number (tree-sitter uses 0-indexed rows)
        line_number = node.start_point[0] + 1
        
        # Extract the first argument (URL)
        url_node = None
        options_node = None
        
        arg_index = 0
        for child in args_node.children:
            if child.type not in ('(', ')', ','):
                if arg_index == 0:
                    url_node = child
                elif arg_index == 1 and child.type == 'object':
                    options_node = child
                arg_index += 1
        
        if not url_node:
            continue
        
        raw_expression = url_node.text.decode('utf-8')
        http_method = "GET"
        is_template = False
        path_params: List[str] = []
        normalized_pattern = ""
        
        # Handle template literal
        if url_node.type == 'template_string':
            is_template = True
            # Get the template string content (without backticks)
            template_content = raw_expression[1:-1]  # Remove surrounding backticks
            normalized_pattern, path_params = _extract_path_params_from_template(template_content)
        # Handle regular string
        elif url_node.type == 'string':
            url_value = _parse_string_node(url_node, code.encode('utf-8'))
            if url_value:
                normalized_pattern = url_value
                is_template = False
                path_params = []
        # Handle concatenation or other expressions - try to extract what we can
        else:
            # For complex expressions, use the raw text as pattern
            normalized_pattern = raw_expression
            is_template = False
        
        # Extract HTTP method from options if present
        if options_node:
            http_method = _extract_http_method_from_options(options_node, code.encode('utf-8'))
        
        fetch_call = FrontendFetchCall(
            file_path=file_path,
            line=line_number,
            raw_expression=raw_expression,
            normalized_pattern=normalized_pattern,
            http_method=http_method,
            is_template=is_template,
            path_params=path_params
        )
        fetches.append(fetch_call)
    
    return fetches


def _extract_path_params_from_template(template_str: str) -> Tuple[str, List[str]]:
    """
    Extract path parameter names from a template literal string and convert to regex pattern.
    
    Args:
        template_str: The raw template string content (without backticks)
        
    Returns:
        Tuple of (normalized_pattern with [^/]+ wildcards, list of param names)
    """
    # Find all ${...} interpolations
    param_pattern = r'\$\{([^}]+)\}'
    params = []
    
    def replace_with_wildcard(match: re.Match) -> str:
        param_expr = match.group(1).strip()
        # Extract just the variable name (handle expressions like user.id -> use last part)
        param_name = param_expr.split('.')[-1]
        params.append(param_name)
        return '[^/]+'
    
    normalized = re.sub(param_pattern, replace_with_wildcard, template_str)
    return normalized, params


def _parse_string_node(node: Node, source_code: bytes) -> str | None:
    """Extract string value from a string node."""
    if node.type == 'string':
        content = node.text.decode('utf-8')
        # Remove quotes
        if (content.startswith("'") and content.endswith("'")) or \
           (content.startswith('"') and content.endswith('"')):
            return content[1:-1]
    return None


def _extract_http_method_from_options(options_node: Node, source_code: bytes) -> str:
    """Extract HTTP method from fetch options object."""
    # Look for method property in the options object
    for child in options_node.children:
        if child.type == 'pair':
            key_node = child.child_by_field_name('key')
            value_node = child.child_by_field_name('value')
            if key_node and value_node:
                key_text = key_node.text.decode('utf-8').strip().strip('"\'')
                if key_text.lower() == 'method':
                    value_text = value_node.text.decode('utf-8').strip().strip('"\'')
                    return value_text.upper()
    return "GET"
