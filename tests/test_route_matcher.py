"""Tests for route matcher logic."""

import pytest
from stackbridge.core.models import BackendRoute, EndpointParam, FrontendEndpointCall, HttpMethod
from stackbridge.core.route_matcher import match_frontend_call_to_routes, normalize_fastapi_path


def test_normalize_fastapi_path():
    pattern = normalize_fastapi_path("/api/v1/users/{user_id}/billing")
    assert pattern == "^/api/v1/users/(?P<user_id>[^/]+)/billing$"


def test_match_static_frontend_call():
    fe_call = FrontendEndpointCall(
        file_path="frontend/UserProfile.tsx",
        line_number=10,
        raw_url="/api/v1/teams",
        normalized_path="/api/v1/teams",
        http_method=HttpMethod.GET,
    )
    be_route = BackendRoute(
        file_path="backend/routes.py",
        line_number=5,
        function_name="get_teams",
        raw_path="/api/v1/teams",
        normalized_path="/api/v1/teams",
        http_methods=[HttpMethod.GET],
    )
    matches = match_frontend_call_to_routes(fe_call, [be_route])
    assert len(matches) == 1
    assert matches[0].function_name == "get_teams"


def test_match_dynamic_frontend_call():
    fe_call = FrontendEndpointCall(
        file_path="frontend/UserProfile.tsx",
        line_number=20,
        raw_url="/api/v1/users/user_123/billing",
        normalized_path="/api/v1/users/{param}/billing",
        http_method=HttpMethod.GET,
    )
    be_route = BackendRoute(
        file_path="backend/routes.py",
        line_number=15,
        function_name="get_user_billing",
        raw_path="/api/v1/users/{user_id}/billing",
        normalized_path="/api/v1/users/{user_id}/billing",
        http_methods=[HttpMethod.GET],
        path_params=[EndpointParam(name="user_id", param_type="path", required=True)],
    )
    matches = match_frontend_call_to_routes(fe_call, [be_route])
    assert len(matches) == 1
    assert matches[0].function_name == "get_user_billing"
