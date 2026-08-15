"""Parser for extracting fetch calls and HTTP client requests from TypeScript / TSX files using Tree-sitter."""

import os
import re
from typing import List, Optional, Tuple
from tree_sitter import Language, Node, Parser
import tree_sitter_typescript as tstypescript

from stackbridge.core.models import FrontendEndpointCall, FrontendFetchCall, HttpMethod


class TypeScriptFetchParser:
    """Extracts fetch / axios / custom client calls from TypeScript/TSX AST."""

    def __init__(self) -> None:
        self.ts_lang = Language(tstypescript.language_typescript())
        self.tsx_lang = Language(tstypescript.language_tsx())
        self.ts_parser = Parser(self.ts_lang)
        self.tsx_parser = Parser(self.tsx_lang)

    def _get_parser_for_file(self, file_path: str) -> Parser:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".tsx", ".jsx"):
            return self.tsx_parser
        return self.ts_parser

    def _parse_method_from_options(self, options_node: Node, source_bytes: bytes) -> HttpMethod:
        """Attempts to find `method: 'POST'` in options object."""
        if options_node.type == "object":
            for child in options_node.children:
                if child.type == "pair":
                    key_node = child.child_by_field_name("key")
                    value_node = child.child_by_field_name("value")
                    if key_node and value_node:
                        key_text = source_bytes[key_node.start_byte:key_node.end_byte].decode("utf-8").strip("'\"")
                        if key_text.lower() == "method":
                            method_str = source_bytes[value_node.start_byte:value_node.end_byte].decode("utf-8").strip("'\"").upper()
                            try:
                                return HttpMethod(method_str)
                            except ValueError:
                                pass
        return HttpMethod.GET

    def _extract_template_string_info(self, template_node: Node, source_bytes: bytes) -> Tuple[str, str, List[str]]:
        """Extracts raw string, normalized path, and parameter names from template literal."""
        raw_text = source_bytes[template_node.start_byte:template_node.end_byte].decode("utf-8")
        
        normalized_parts: List[str] = []
        path_params: List[str] = []

        for child in template_node.children:
            if child.type == "string_fragment":
                fragment = source_bytes[child.start_byte:child.end_byte].decode("utf-8")
                normalized_parts.append(fragment)
            elif child.type == "template_substitution":
                sub_expr = None
                for sub_child in child.children:
                    if sub_child.type not in ("${", "}") and sub_child.is_named:
                        sub_expr = source_bytes[sub_child.start_byte:sub_child.end_byte].decode("utf-8").strip()
                        break
                if not sub_expr:
                    raw_sub = source_bytes[child.start_byte:child.end_byte].decode("utf-8")
                    sub_expr = raw_sub.lstrip("${").rstrip("}").strip()
                
                param_name = sub_expr
                path_params.append(param_name)
                normalized_parts.append(f"{{{param_name}}}")

        normalized_path = "".join(normalized_parts)
        return raw_text, normalized_path, path_params

    def parse_code(self, source_code: str, file_path: str = "component.tsx") -> List[FrontendEndpointCall]:
        """Parses TypeScript/TSX code string and returns detected frontend endpoint calls."""
        parser = self._get_parser_for_file(file_path)
        source_bytes = source_code.encode("utf-8")
        tree = parser.parse(source_bytes)
        calls: List[FrontendEndpointCall] = []

        def traverse(node: Node) -> None:
            if node.type == "call_expression":
                func = node.child_by_field_name("function")
                args = node.child_by_field_name("arguments")
                
                if func and args and func.type == "identifier":
                    func_name = source_bytes[func.start_byte:func.end_byte].decode("utf-8")
                    if func_name == "fetch" and len(args.named_children) > 0:
                        first_arg = args.named_children[0]
                        line_number = node.start_point.row + 1
                        
                        http_method = HttpMethod.GET
                        if len(args.named_children) > 1:
                            http_method = self._parse_method_from_options(args.named_children[1], source_bytes)

                        if first_arg.type == "string":
                            raw_val = source_bytes[first_arg.start_byte:first_arg.end_byte].decode("utf-8")
                            cleaned_url = raw_val.strip("'\"`")
                            calls.append(
                                FrontendEndpointCall(
                                    file_path=file_path,
                                    line_number=line_number,
                                    raw_url=cleaned_url,
                                    normalized_path=cleaned_url,
                                    http_method=http_method,
                                    path_params=[],
                                    is_template=False,
                                )
                            )
                        elif first_arg.type == "template_string":
                            raw_text, normalized_path, path_params = self._extract_template_string_info(
                                first_arg, source_bytes
                            )
                            calls.append(
                                FrontendEndpointCall(
                                    file_path=file_path,
                                    line_number=line_number,
                                    raw_url=raw_text,
                                    normalized_path=normalized_path,
                                    http_method=http_method,
                                    path_params=path_params,
                                    is_template=True,
                                )
                            )

            for child in node.children:
                traverse(child)

        traverse(tree.root_node)
        return calls

    def parse_file(self, file_path: str) -> List[FrontendEndpointCall]:
        """Parses a TypeScript/TSX file from filesystem and returns detected frontend endpoint calls."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self.parse_code(content, file_path=file_path)


# Compatibility helper functions

def _extract_path_params_from_template(template_str: str) -> Tuple[str, List[str]]:
    param_pattern = r'\$\{([^}]+)\}'
    params = []
    
    def replace_with_wildcard(match: re.Match) -> str:
        param_expr = match.group(1).strip()
        param_name = param_expr.split('.')[-1]
        params.append(param_name)
        return '[^/]+'
    
    normalized = re.sub(param_pattern, replace_with_wildcard, template_str)
    return normalized, params


def _parse_string_node(node: Node, source_code: bytes) -> Optional[str]:
    if node.type == 'string':
        content = node.text.decode('utf-8')
        if (content.startswith("'") and content.endswith("'")) or \
           (content.startswith('"') and content.endswith('"')):
            return content[1:-1]
    return None


def _extract_http_method_from_options(options_node: Node, source_code: bytes) -> str:
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


def extract_nextjs_fetches(code: str, file_path: str) -> List[FrontendFetchCall]:
    """Extract fetch() calls from TypeScript/TSX code using Tree-sitter."""
    parser_obj = TypeScriptFetchParser()
    calls = parser_obj.parse_code(code, file_path=file_path)
    fetches: List[FrontendFetchCall] = []
    for c in calls:
        method_str = c.http_method.value if isinstance(c.http_method, HttpMethod) else str(c.http_method)
        fetches.append(
            FrontendFetchCall(
                file_path=c.file_path,
                line=c.line_number,
                raw_expression=c.raw_url,
                normalized_pattern=c.normalized_path,
                http_method=method_str,
                is_template=c.is_template,
                path_params=c.path_params,
            )
        )
    return fetches
