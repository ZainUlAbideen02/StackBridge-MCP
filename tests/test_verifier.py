"""Tests for compiler-level verifiers, baseline diffing, and VerifierEngine."""

from pathlib import Path

import pytest

from stackbridge.core.graph import StackGraph
from stackbridge.verifier.engine import VerifierEngine
from stackbridge.verifier.py_checker import DiagnosticError, PythonTypeVerifier

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"
MODELS_FIXTURE = FIXTURES_DIR / "backend" / "models.py"
ROUTES_FIXTURE = FIXTURES_DIR / "backend" / "routes.py"


@pytest.fixture
def baseline_files():
    with open(MODELS_FIXTURE, "r", encoding="utf-8") as f:
        models_code = f.read()
    with open(ROUTES_FIXTURE, "r", encoding="utf-8") as f:
        routes_code = f.read()
    return {
        "backend/models.py": models_code,
        "backend/routes.py": routes_code,
    }


def test_python_type_verifier_detects_removed_field(baseline_files):
    verifier = PythonTypeVerifier()

    # In baseline, there are no schema errors
    baseline_diags = verifier.verify_files(baseline_files)
    assert len(baseline_diags) == 0

    # Modify models.py by removing the `plan` field from BillingAccount
    modified_models = baseline_files["backend/models.py"].replace(
        'plan = Column(String, nullable=False, default="free")',
        '# plan field removed',
    )
    current_files = {
        "backend/models.py": modified_models,
        "backend/routes.py": baseline_files["backend/routes.py"],
    }

    # Verify that routes.py references billing.plan and triggers a DiagnosticError
    diff_diags = verifier.verify_with_diff(
        current_files=current_files,
        baseline_files=baseline_files,
    )

    assert len(diff_diags) == 1
    err = diff_diags[0]
    assert isinstance(err, DiagnosticError)
    assert err.file_path == "backend/routes.py"
    assert "plan" in err.message
    assert "BillingAccount" in err.message


def test_python_type_verifier_filters_baseline_errors(baseline_files):
    verifier = PythonTypeVerifier()

    # Introduce a pre-existing error in baseline routes.py (referencing non-existent `old_field`)
    buggy_baseline_routes = baseline_files["backend/routes.py"] + "\n# access non-existent\nx = billing.old_field\n"
    flawed_baseline = {
        "backend/models.py": baseline_files["backend/models.py"],
        "backend/routes.py": buggy_baseline_routes,
    }

    # Baseline itself has 1 error
    base_diags = verifier.verify_files(flawed_baseline)
    assert len(base_diags) == 1
    assert "old_field" in base_diags[0].message

    # Now make a change that removes `plan`
    modified_models = baseline_files["backend/models.py"].replace(
        'plan = Column(String, nullable=False, default="free")',
        '# plan removed',
    )
    current_files = {
        "backend/models.py": modified_models,
        "backend/routes.py": buggy_baseline_routes,
    }

    # verify_with_diff should only report the NEW `plan` error and filter out `old_field`
    diff_diags = verifier.verify_with_diff(
        current_files=current_files,
        baseline_files=flawed_baseline,
    )

    assert len(diff_diags) == 1
    assert "plan" in diff_diags[0].message
    assert "old_field" not in diff_diags[0].message


def test_verifier_engine_verify_impacted_files(baseline_files):
    engine = VerifierEngine(repo_path=FIXTURES_DIR)
    graph = StackGraph.build_from_repo(str(FIXTURES_DIR))

    # Remove `plan` field from models.py
    modified_models = baseline_files["backend/models.py"].replace(
        'plan = Column(String, nullable=False, default="free")',
        '# plan field deleted',
    )

    report = engine.verify_impacted_files(
        modified_files={"backend/models.py": modified_models},
        repo_path=FIXTURES_DIR,
        graph=graph,
    )

    assert report.has_breakage is True
    assert report.error_count == 1
    assert len(report.diagnostics) == 1
    assert "plan" in report.diagnostics[0].message

    # Verify that blast-radius discovered upstream impacted files
    assert "backend/routes.py" in report.impacted_files
    assert "frontend/UserProfile.tsx" in report.impacted_files


def test_verifier_engine_compatible_change_no_breakage(baseline_files):
    engine = VerifierEngine(repo_path=FIXTURES_DIR)
    graph = StackGraph.build_from_repo(str(FIXTURES_DIR))

    # Add a new column to models.py (backward compatible)
    compatible_models = baseline_files["backend/models.py"] + "\n    tier = Column(String, default='standard')\n"

    report = engine.verify_impacted_files(
        modified_files={"backend/models.py": compatible_models},
        repo_path=FIXTURES_DIR,
        graph=graph,
    )

    assert report.has_breakage is False
    assert report.error_count == 0
    assert len(report.diagnostics) == 0
