"""Matching engine between frontend fetch calls and backend routes with AST-aware confidence scoring."""

import re
from typing import Dict, List, Optional, Tuple, Union
from stackbridge.core.models import (
    BackendRoute,
    FastAPIRoute,
    FrontendEndpointCall,
    FrontendFetchCall,
    HttpMethod,
    RouteMatchResult,
)


def normalize_fastapi_path(path: str) -> str:
    """Converts FastAPI route format like /api/v1/users/{user_id}/billing to regex pattern."""
    cleaned = path.rstrip("/") if len(path) > 1 else path
    pattern = re.sub(r"\{([a-zA-Z0-9_]+)(?::[^}]+)?\}", r"(?P<\1>[^/]+)", cleaned)
    return f"^{pattern}$"


def _split_segments(path: str) -> List[str]:
    """Splits a URL path into normalized non-empty segment tokens."""
    clean_path = path.split("?")[0].strip()
    clean_path = clean_path.strip("'\"`")
    segments = [s for s in clean_path.split("/") if s]
    return segments


def _is_param_segment(segment: str) -> Tuple[bool, str]:
    """Checks if a segment is a parameter placeholder (e.g. {userId}, ${userId}, :userId)."""
    seg = segment.strip()
    if (seg.startswith("{") and seg.endswith("}")) or (seg.startswith("${") and seg.endswith("}")):
        name = seg.lstrip("${").rstrip("}")
        return True, name
    if seg.startswith(":"):
        return True, seg[1:]
    return False, ""


def calculate_route_confidence(
    fe_path: str, be_path: str, fe_method: Union[HttpMethod, str], be_methods: List[Union[HttpMethod, str]]
) -> Tuple[float, Dict[str, str]]:
    """
    Calculates the confidence score (0.0 to 1.0) and parameter mappings between frontend call and backend route.
    
    Scoring model:
    - Static identical segment: 1.0
    - Dynamic parameter segment: 0.40
    - Mismatched static segment or mismatched method: 0.0
    """
    fe_method_str = fe_method.value if isinstance(fe_method, HttpMethod) else str(fe_method).upper()
    be_method_strs = [
        m.value if isinstance(m, HttpMethod) else str(m).upper() for m in be_methods
    ]

    if fe_method_str not in be_method_strs:
        return 0.0, {}

    fe_segments = _split_segments(fe_path)
    be_segments = _split_segments(be_path)

    if len(fe_segments) != len(be_segments):
        return 0.0, {}

    if not fe_segments and not be_segments:
        return 1.0, {}

    segment_scores: List[float] = []
    param_mappings: Dict[str, str] = {}

    for fe_seg, be_seg in zip(fe_segments, be_segments):
        fe_is_param, fe_param_name = _is_param_segment(fe_seg)
        be_is_param, be_param_name = _is_param_segment(be_seg)

        if not fe_is_param and not be_is_param:
            if fe_seg == be_seg:
                segment_scores.append(1.0)
            else:
                return 0.0, {}
        elif fe_is_param and be_is_param:
            param_mappings[fe_param_name] = be_param_name
            segment_scores.append(0.40)
        elif not fe_is_param and be_is_param:
            param_mappings[fe_seg] = be_param_name
            segment_scores.append(0.40)
        else:
            return 0.0, {}

    total_score = sum(segment_scores)
    confidence = round(total_score / len(fe_segments), 2)
    return confidence, param_mappings


def match_frontend_call_to_routes(
    call: FrontendEndpointCall, routes: List[BackendRoute], min_confidence: float = 0.5
) -> List[RouteMatchResult]:
    """Matches a frontend fetch call to backend routes and ranks by confidence."""
    matches: List[RouteMatchResult] = []

    target_path = call.normalized_path if call.normalized_path else call.raw_url

    for route in routes:
        confidence, param_mappings = calculate_route_confidence(
            fe_path=target_path,
            be_path=route.normalized_path,
            fe_method=call.http_method,
            be_methods=route.http_methods,
        )

        if confidence >= min_confidence:
            matches.append(
                RouteMatchResult(
                    frontend_call=call,
                    backend_route=route,
                    confidence=confidence,
                    is_exact=(confidence == 1.0),
                    param_mappings=param_mappings,
                    match_strategy="ast_segment_scoring",
                )
            )

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


# Qwen compatibility functions

def _normalize_path_for_comparison(path: str) -> str:
    return path.rstrip("/") if len(path) > 1 else path


def _count_path_segments(pattern: str) -> int:
    cleaned = pattern.strip("/")
    if not cleaned:
        return 0
    return len(cleaned.split("/"))


def _paths_match(fetch_pattern: str, route_regex: str) -> bool:
    try:
        return bool(re.match(route_regex, fetch_pattern))
    except re.error:
        return False


def match_routes(
    fetches: List[FrontendFetchCall],
    routes: List[FastAPIRoute],
    api_prefix_strip: Optional[str] = "/api"
) -> List[RouteMatchResult]:
    """Match frontend fetch calls to backend FastAPI routes."""
    results: List[RouteMatchResult] = []
    
    for fetch in fetches:
        best_match: Optional[RouteMatchResult] = None
        best_confidence = 0.0
        
        fetch_pattern = fetch.normalized_pattern
        if api_prefix_strip and fetch_pattern.startswith(api_prefix_strip):
            fetch_pattern = fetch_pattern[len(api_prefix_strip):]
            if not fetch_pattern.startswith("/"):
                fetch_pattern = "/" + fetch_pattern
        
        for route in routes:
            if fetch.http_method.upper() != route.http_method.upper():
                continue
            
            route_regex = route.normalized_regex
            if not _paths_match(fetch_pattern, route_regex):
                continue
            
            confidence = 0.0
            match_strategy = ""
            notes: Optional[str] = None
            
            if not fetch.is_template and not route.path_params:
                fetch_normalized = _normalize_path_for_comparison(fetch_pattern)
                route_normalized = _normalize_path_for_comparison(route.route_path)
                if fetch_normalized == route_normalized:
                    confidence = 1.0
                    match_strategy = "exact_static_match"
                    notes = "Exact method and static path match"
            
            if fetch.is_template or route.path_params:
                fetch_segments = _count_path_segments(fetch_pattern)
                route_segments = _count_path_segments(route.route_path)
                
                if fetch_segments == route_segments and _paths_match(fetch_pattern, route_regex):
                    confidence = 0.88
                    match_strategy = "template_slug_alignment"
                    param_notes = []
                    if fetch.path_params:
                        param_notes.append(f"frontend params: {fetch.path_params}")
                    if route.path_params:
                        param_notes.append(f"backend params: {route.path_params}")
                    notes = "; ".join(param_notes) if param_notes else "Template path alignment"
            
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = RouteMatchResult(
                    frontend_call=fetch,
                    backend_route=route,
                    confidence=confidence,
                    is_exact=(confidence == 1.0),
                    match_strategy=match_strategy,
                    notes=notes
                )
        
        if best_match:
            results.append(best_match)
    
    return results
