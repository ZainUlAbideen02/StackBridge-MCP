"""Tests for AST route extraction and confidence scoring across Next.js and FastAPI fixtures."""

import os
import pytest
from pathlib import Path

from stackbridge.core.models import BackendRoute, FrontendEndpointCall, HttpMethod
from stackbridge.core.route_matcher import (
    calculate_route_confidence,
    match_frontend_call_to_routes,
    normalize_fastapi_path,
)
from stackbridge.parsers.py_route_parser import PythonRouteParser
from stackbridge.parsers.ts_fetch_parser import TypeScriptFetchParser


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"
FRONTEND_FIXTURE = FIXTURES_DIR / "frontend" / "UserProfile.tsx"
BACKEND_FIXTURE = FIXTURES_DIR / "backend" / "routes.py"


@pytest.fixture
def extracted_frontend_calls():
    parser = TypeScriptFetchParser()
    assert FRONTEND_FIXTURE.exists(), f"Frontend fixture not found at {FRONTEND_FIXTURE}"
    calls = parser.parse_file(str(FRONTEND_FIXTURE))
    return calls


@pytest.fixture
def extracted_backend_routes():
    parser = PythonRouteParser()
    assert BACKEND_FIXTURE.exists(), f"Backend fixture not found at {BACKEND_FIXTURE}"
    routes = parser.parse_file(str(BACKEND_FIXTURE))
    return routes


def test_ast_frontend_extraction(extracted_frontend_calls):
    assert len(extracted_frontend_calls) == 2

    # Verify static fetch call
    static_call = next(c for c in extracted_frontend_calls if not c.is_template)
    assert static_call.raw_url == "/api/v1/teams"
    assert static_call.http_method == HttpMethod.GET
    assert static_call.line_number == 26

    # Verify template string fetch call
    template_call = next(c for c in extracted_frontend_calls if c.is_template)
    assert "/api/v1/users/" in template_call.raw_url
    assert "${userId}" in template_call.raw_url
    assert template_call.normalized_path == "/api/v1/users/{userId}/billing"
    assert template_call.path_params == ["userId"]
    assert template_call.http_method == HttpMethod.GET
    assert template_call.line_number == 33


def test_ast_backend_extraction(extracted_backend_routes):
    assert len(extracted_backend_routes) == 2

    # Verify teams route
    teams_route = next(r for r in extracted_backend_routes if r.function_name == "get_teams")
    assert teams_route.raw_path == "/api/v1/teams"
    assert teams_route.normalized_path == "/api/v1/teams"
    assert teams_route.http_methods == [HttpMethod.GET]
    assert teams_route.line_number == 23

    # Verify billing route
    billing_route = next(r for r in extracted_backend_routes if r.function_name == "get_user_billing")
    assert billing_route.raw_path == "/api/v1/users/{user_id}/billing"
    assert billing_route.normalized_path == "/api/v1/users/{user_id}/billing"
    assert billing_route.http_methods == [HttpMethod.GET]
    assert len(billing_route.path_params) == 1
    assert billing_route.path_params[0].name == "user_id"
    assert billing_route.line_number == 30


def test_match_static_teams_route(extracted_frontend_calls, extracted_backend_routes):
    static_call = next(c for c in extracted_frontend_calls if not c.is_template)
    matches = match_frontend_call_to_routes(static_call, extracted_backend_routes)

    assert len(matches) == 1
    match = matches[0]
    assert match.backend_route.function_name == "get_teams"
    assert match.backend_route.normalized_path == "/api/v1/teams"
    assert match.confidence == 1.0
    assert match.is_exact is True


def test_match_dynamic_template_billing_route(extracted_frontend_calls, extracted_backend_routes):
    template_call = next(c for c in extracted_frontend_calls if c.is_template)
    matches = match_frontend_call_to_routes(template_call, extracted_backend_routes)

    assert len(matches) == 1
    match = matches[0]
    assert match.backend_route.function_name == "get_user_billing"
    assert match.backend_route.normalized_path == "/api/v1/users/{user_id}/billing"
    assert match.confidence == 0.88
    assert match.is_exact is False
    assert match.param_mappings.get("userId") == "user_id"


def test_non_matching_routes_no_false_positives(extracted_backend_routes):
    # Unrelated path
    unrelated_call = FrontendEndpointCall(
        file_path="frontend/Orders.tsx",
        line_number=12,
        raw_url="/api/v1/orders/123",
        normalized_path="/api/v1/orders/123",
        http_method=HttpMethod.GET,
    )
    matches = match_frontend_call_to_routes(unrelated_call, extracted_backend_routes)
    assert len(matches) == 0

    # Mismatched HTTP method
    post_call = FrontendEndpointCall(
        file_path="frontend/UserProfile.tsx",
        line_number=40,
        raw_url="/api/v1/teams",
        normalized_path="/api/v1/teams",
        http_method=HttpMethod.POST,
    )
    post_matches = match_frontend_call_to_routes(post_call, extracted_backend_routes)
    assert len(post_matches) == 0

    # Path segment count mismatch
    short_call = FrontendEndpointCall(
        file_path="frontend/UserProfile.tsx",
        line_number=45,
        raw_url="/api/v1/users",
        normalized_path="/api/v1/users",
        http_method=HttpMethod.GET,
    )
    short_matches = match_frontend_call_to_routes(short_call, extracted_backend_routes)
    assert len(short_matches) == 0


def test_normalize_fastapi_path():
    pattern = normalize_fastapi_path("/api/v1/users/{user_id}/billing")
    assert pattern == "^/api/v1/users/(?P<user_id>[^/]+)/billing$"
