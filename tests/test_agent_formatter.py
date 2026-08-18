"""Tests for AgentDiagnosticFormatter and Two-Tier mtime/size Caching."""

import os
from pathlib import Path
import time
import pytest
from unittest.mock import patch

from stackbridge.core.indexer import IncrementalIndexer
from stackbridge.parsers.parallel_parser import ParallelASTParser
from stackbridge.verifier.agent_formatter import AgentDiagnosticFormatter
from stackbridge.verifier.py_checker import DiagnosticError


def test_agent_formatter_safe_clean_report():
    """Verify AgentDiagnosticFormatter formats empty diagnostics into 🟢 SAFE status."""
    report = AgentDiagnosticFormatter.format_breakage_report(diagnostics=[], repo_path=".")
    assert "🟢 SAFE" in report
    assert "0 breaking changes detected" in report
    assert "Clean" in report


def test_agent_formatter_breaking_and_drift_with_snippets(tmp_path: Path):
    """Verify AgentDiagnosticFormatter formats 🔴 BREAKING and 🟡 DRIFT with 3-line snippets and pointers."""
    test_file = tmp_path / "routes.py"
    test_file.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/api/users')\n"
        "def get_users(db = Depends(get_db)):\n"
        "    user = db.query(User).first()\n"
        "    return {'status': user.non_existent_field}\n"
        "def helper():\n"
        "    pass\n",
        encoding="utf-8",
    )

    breaking_diag = DiagnosticError(
        file_path=str(test_file),
        line=6,
        column=23,
        message="Attribute 'non_existent_field' does not exist on model 'User'",
        rule="schema-attribute-missing",
        severity="error",
        source="python",
    )

    drift_diag = DiagnosticError(
        file_path=str(test_file),
        line=3,
        column=1,
        message="Route path '/api/users' has altered response model structure",
        rule="schema-drift-warning",
        severity="warning",
        source="python",
    )

    report = AgentDiagnosticFormatter.format_breakage_report(
        diagnostics=[breaking_diag, drift_diag],
        repo_path=str(tmp_path),
    )

    # 1. Severity Headers
    assert "🔴 BREAKING" in report
    assert "🟡 DRIFT" in report

    # 2. Line numbers and '>' pointer in snippet
    assert "6 |     return {'status': user.non_existent_field}" in report
    assert ">" in report
    assert "5 |     user = db.query(User).first()" in report
    assert "7 | def helper():" in report

    # 3. Suggested fix
    assert "Suggested Fix" in report
    assert "Model Schema Alignment" in report or "Remediation" in report


def test_two_tier_mtime_caching_skips_sha256_recalculation(tmp_path: Path):
    """Verify that tier 1 (mtime, size) match skips SHA-256 hashing entirely on warm index runs."""
    repo = tmp_path / "repo"
    repo.mkdir()

    backend = repo / "backend"
    backend.mkdir()
    app_py = backend / "app.py"
    app_py.write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/v1/ping')\ndef ping(): return {'pong': True}\n",
        encoding="utf-8",
    )

    cache_path = tmp_path / "cache.json"
    indexer = IncrementalIndexer(repo_path=repo, cache_path=cache_path)

    # First run (Cold): parses file and stores mtime & size
    graph1, report1 = indexer.index(use_cache=True)
    assert report1.total_files == 1
    assert report1.modified_files == 1
    assert cache_path.exists()

    # Second run (Warm / Unchanged): mtime & size match -> tier-1 fast hit, skips _compute_sha256 and parse_files
    with patch.object(IncrementalIndexer, "_compute_sha256", wraps=IncrementalIndexer._compute_sha256) as spy_sha:
        with patch.object(ParallelASTParser, "parse_files", wraps=indexer.parallel_parser.parse_files) as spy_parse:
            graph2, report2 = indexer.index(use_cache=True)
            assert report2.total_files == 1
            assert report2.modified_files == 0
            assert report2.cached_files_hit == 1
            # Tier 1 fast hit: 0 calls to _compute_sha256 and 0 calls to parse_files
            assert spy_sha.call_count == 0
            assert spy_parse.call_count == 0

    # Tier 2: Change mtime but keep content identical -> triggers tier 2 SHA-256 check
    new_mtime = time.time() + 1000
    os.utime(str(app_py), (new_mtime, new_mtime))
    with patch.object(IncrementalIndexer, "_compute_sha256", wraps=IncrementalIndexer._compute_sha256) as spy_sha:
        with patch.object(ParallelASTParser, "parse_files", wraps=indexer.parallel_parser.parse_files) as spy_parse:
            graph3, report3 = indexer.index(use_cache=True)
            assert report3.total_files == 1
            assert report3.modified_files == 0
            assert report3.cached_files_hit == 1
            # Tier 2 hit: _compute_sha256 called once, but file NOT re-parsed!
            assert spy_sha.call_count == 1
            assert spy_parse.call_count == 0
