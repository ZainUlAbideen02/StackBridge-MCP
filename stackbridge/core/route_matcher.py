"""Matching engine between frontend fetch calls and backend routes."""

import re
from typing import List, Optional, Tuple
from stackbridge.core.models import FrontendEndpointCall, BackendRoute


def normalize_fastapi_path(path: str) -> str:
    """Converts FastAPI route format like /api/v1/users/{user_id}/billing to regex pattern / normalized format."""
    # Strip trailing slash except if path is just "/"
    cleaned = path.rstrip("/") if len(path) > 1 else path
    # Replace {param} or {param:path} with regex wildcard or placeholder
    pattern = re.sub(r"\{([a-zA-Z0-9_]+)(?::[^}]+)?\}", r"(?P<\1>[^/]+)", cleaned)
    return f"^{pattern}$"


def match_frontend_call_to_routes(
    call: FrontendEndpointCall, routes: List[BackendRoute]
) -> List[BackendRoute]:
    """Matches a frontend fetch call to candidate backend routes."""
    matches: List[BackendRoute] = []
    # Normalize call path
    call_path = call.raw_url.split("?")[0].rstrip("/") if len(call.raw_url.split("?")[0]) > 1 else call.raw_url.split("?")[0]

    for route in routes:
        if call.http_method in route.http_methods:
            pattern = normalize_fastapi_path(route.raw_path)
            if re.match(pattern, call_path):
                matches.append(route)
    return matches
