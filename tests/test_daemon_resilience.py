"""Tests for verifier daemon concurrency locking, timeout enforcement, and crash auto-recovery."""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

from stackbridge.verifier.engine import VerifierEngine
from stackbridge.verifier.py_checker import DiagnosticError


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "synthetic_fullstack"
MODELS_FIXTURE = FIXTURES_DIR / "backend" / "models.py"


@pytest.fixture
def baseline_models_code():
    with open(MODELS_FIXTURE, "r", encoding="utf-8") as f:
        return f.read()


def test_concurrent_verification_locking(baseline_models_code):
    """Verify that concurrent verification requests from 2 threads queue safely without race conditions."""
    engine = VerifierEngine(repo_path=FIXTURES_DIR)

    modified_code_1 = baseline_models_code.replace(
        'plan = Column(String, nullable=False, default="free")',
        '# removed plan',
    )
    modified_code_2 = baseline_models_code + "\n    custom_field = Column(String)\n"

    results = []

    def run_verify(mod_content):
        return engine.verify_impacted_files(
            modified_files={"backend/models.py": mod_content},
            repo_path=FIXTURES_DIR,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_verify, modified_code_1)
        f2 = executor.submit(run_verify, modified_code_2)

        r1 = f1.result(timeout=10.0)
        r2 = f2.result(timeout=10.0)
        results.extend([r1, r2])

    assert len(results) == 2
    # One had breakage (plan removed), one had no breakage (custom_field added)
    breakage_reports = [r for r in results if r.has_breakage]
    clean_reports = [r for r in results if not r.has_breakage]

    assert len(breakage_reports) == 1
    assert len(clean_reports) == 1
    assert breakage_reports[0].error_count == 1
    assert clean_reports[0].error_count == 0


def test_daemon_timeout_recovery_and_respawn(baseline_models_code):
    """Verify that timeout triggers restart_daemon and returns DAEMON_RECOVERED, with clean subsequent run."""
    # Set a tiny timeout to force a timeout
    engine = VerifierEngine(repo_path=FIXTURES_DIR, timeout_seconds=0.001)

    # Make the verifier sleep longer than the timeout
    original_verify = engine.py_verifier.verify_with_diff

    def slow_verify(*args, **kwargs):
        time.sleep(0.05)
        return original_verify(*args, **kwargs)

    engine.py_verifier.verify_with_diff = slow_verify

    # 1. First call should timeout and auto-recover
    report_timeout = engine.verify_impacted_files(
        modified_files={"backend/models.py": baseline_models_code},
        repo_path=FIXTURES_DIR,
    )

    assert report_timeout.has_breakage is True
    assert report_timeout.error_count == 1
    diag = report_timeout.diagnostics[0]
    assert diag.rule == "DAEMON_RECOVERED"
    assert "DAEMON_RECOVERED" in diag.message
    assert diag.source == "dmypy"

    # 2. Subsequent call on fresh engine/daemon succeeds with standard timeout
    engine.timeout_seconds = 6.0
    report_normal = engine.verify_impacted_files(
        modified_files={"backend/models.py": baseline_models_code},
        repo_path=FIXTURES_DIR,
    )

    assert report_normal.has_breakage is False
    assert report_normal.error_count == 0


def test_daemon_crash_recovery_and_shadow_cleanup(tmp_path, baseline_models_code):
    """Verify that an unexpected daemon crash triggers clean restart and removes shadow files."""
    engine = VerifierEngine(repo_path=FIXTURES_DIR, timeout_seconds=6.0)

    # Create a shadow file and register it in engine
    shadow_file = tmp_path / "shadow_test.py"
    shadow_file.write_text("print('shadow')", encoding="utf-8")
    assert shadow_file.exists()
    engine._shadow_files.add(str(shadow_file))

    # Simulate crash in python verifier
    def crash_verify(*args, **kwargs):
        raise RuntimeError("dmypy daemon crashed with SIGSEGV (139)")

    engine.py_verifier.verify_with_diff = crash_verify

    # 1. Execution should catch crash, trigger restart_daemon, clean shadow files, and report DAEMON_RECOVERED
    report_crash = engine.verify_impacted_files(
        modified_files={"backend/models.py": baseline_models_code},
        repo_path=FIXTURES_DIR,
    )

    assert report_crash.has_breakage is True
    assert report_crash.error_count == 1
    diag = report_crash.diagnostics[0]
    assert diag.rule == "DAEMON_RECOVERED"
    assert "crash/error" in diag.message
    assert not shadow_file.exists(), "Shadow file was not cleaned up during daemon restart"
    assert len(engine._shadow_files) == 0

    # 2. Verify subsequent call succeeds cleanly with the newly respawned daemon
    report_respawned = engine.verify_impacted_files(
        modified_files={"backend/models.py": baseline_models_code},
        repo_path=FIXTURES_DIR,
    )
    assert report_respawned.has_breakage is False
    assert report_respawned.error_count == 0
