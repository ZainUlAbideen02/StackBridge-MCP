"""Matching engine between frontend fetch calls and backend routes."""

import re
from typing import List, Optional
from stackbridge.core.models import FrontendFetchCall, FastAPIRoute, RouteMatchResult


def _normalize_path_for_comparison(path: str) -> str:
    """Normalize a path for comparison by stripping trailing slashes."""
    return path.rstrip("/") if len(path) > 1 else path


def _count_path_segments(pattern: str) -> int:
    """Count the number of segments in a path pattern."""
    # Remove leading/trailing slashes and split
    cleaned = pattern.strip("/")
    if not cleaned:
        return 0
    return len(cleaned.split("/"))


def _paths_match(fetch_pattern: str, route_regex: str) -> bool:
    """Check if a fetch pattern matches a route regex."""
    try:
        return bool(re.match(route_regex, fetch_pattern))
    except re.error:
        return False


def match_routes(
    fetches: List[FrontendFetchCall],
    routes: List[FastAPIRoute],
    api_prefix_strip: Optional[str] = "/api"
) -> List[RouteMatchResult]:
    """
    Match frontend fetch calls to backend FastAPI routes.
    
    Args:
        fetches: List of frontend fetch calls extracted from TypeScript/TSX
        routes: List of backend routes extracted from Python/FastAPI
        api_prefix_strip: Optional API prefix to strip from fetch patterns before matching
        
    Returns:
        List of RouteMatchResult objects representing matches with confidence scores
    """
    results: List[RouteMatchResult] = []
    
    for fetch in fetches:
        best_match: Optional[RouteMatchResult] = None
        best_confidence = 0.0
        
        # Strip API prefix if configured
        fetch_pattern = fetch.normalized_pattern
        if api_prefix_strip and fetch_pattern.startswith(api_prefix_strip):
            fetch_pattern = fetch_pattern[len(api_prefix_strip):]
            if not fetch_pattern.startswith("/"):
                fetch_pattern = "/" + fetch_pattern
        
        for route in routes:
            # Rule: Reject if HTTP methods conflict
            if fetch.http_method.upper() != route.http_method.upper():
                continue
            
            # Get the route's regex pattern (already normalized)
            route_regex = route.normalized_regex
            
            # Check if paths match
            if not _paths_match(fetch_pattern, route_regex):
                continue
            
            # Calculate confidence score
            confidence = 0.0
            match_strategy = ""
            notes: Optional[str] = None
            
            # Exact static path match (no template variables on either side)
            if not fetch.is_template and not route.path_params:
                # Direct string comparison after normalization
                fetch_normalized = _normalize_path_for_comparison(fetch_pattern)
                route_normalized = _normalize_path_for_comparison(route.route_path)
                if fetch_normalized == route_normalized:
                    confidence = 1.0
                    match_strategy = "exact_static_match"
                    notes = "Exact method and static path match"
            
            # Template literal slug alignment
            if fetch.is_template or route.path_params:
                # Compare segment counts and verify regex match
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
            
            # Only keep this match if it has higher confidence than previous
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = RouteMatchResult(
                    frontend_call=fetch,
                    backend_route=route,
                    confidence=confidence,
                    match_strategy=match_strategy,
                    notes=notes
                )
        
        # Add the best match for this fetch call (if any)
        if best_match:
            results.append(best_match)
    
    return results
