"""Matching engine between frontend fetch calls and backend routes with AST-aware confidence scoring."""

import re
from typing import Dict, List, Optional, Tuple
from stackbridge.core.models import BackendRoute, FrontendEndpointCall, HttpMethod, RouteMatchResult


def normalize_fastapi_path(path: str) -> str:
    """Converts FastAPI route format like /api/v1/users/{user_id}/billing to regex pattern."""
    cleaned = path.rstrip("/") if len(path) > 1 else path
    pattern = re.sub(r"\{([a-zA-Z0-9_]+)(?::[^}]+)?\}", r"(?P<\1>[^/]+)", cleaned)
    return f"^{pattern}$"


def _split_segments(path: str) -> List[str]:
    """Splits a URL path into normalized non-empty segment tokens."""
    # Strip query parameters or trailing slashes
    clean_path = path.split("?")[0].strip()
    # Strip quotes/backticks
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
    fe_path: str, be_path: str, fe_method: HttpMethod, be_methods: List[HttpMethod]
) -> Tuple[float, Dict[str, str]]:
    """
    Calculates the confidence score (0.0 to 1.0) and parameter mappings between frontend call and backend route.
    
    Scoring model:
    - Static identical segment: 1.0
    - Dynamic parameter segment: 0.40
    - Mismatched static segment or mismatched method: 0.0
    """
    if fe_method not in be_methods:
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
            # Concrete value matching a backend parameter slot
            param_mappings[fe_seg] = be_param_name
            segment_scores.append(0.40)
        else:
            # Frontend has parameter but backend is static
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
                )
            )

    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches
