"""Tests for High-Scale Indexer, SHA-256 Incremental Caching, Ignore Rules, and Parallel AST Parsing."""

import shutil
from pathlib import Path

from stackbridge.core.indexer import IncrementalIndexer
from stackbridge.parsers.parallel_parser import ParallelASTParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ADVANCED_FIXTURE_DIR = FIXTURES_DIR / "advanced_fullstack"
SYNTHETIC_FIXTURE_DIR = FIXTURES_DIR / "synthetic_fullstack"


def test_ignore_rules_and_gitignore(tmp_path: Path):
    """Verify default ignore patterns (node_modules, .venv, etc.) and custom .gitignore rules."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create valid files
    (repo / "backend").mkdir()
    (repo / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/health')\ndef health(): return {'ok': True}\n",
        encoding="utf-8",
    )
    (repo / "frontend").mkdir()
    (repo / "frontend" / "App.tsx").write_text(
        "export function App() { fetch('/api/health'); return <div>Health</div>; }\n",
        encoding="utf-8",
    )

    # Create ignored directories and files
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "bad.js").write_text("fetch('/ignored/node');", encoding="utf-8")

    (repo / ".venv").mkdir()
    (repo / ".venv" / "site.py").write_text("@app.get('/ignored/venv')\ndef v(): pass", encoding="utf-8")

    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "cached.py").write_text("# cache", encoding="utf-8")

    # Create custom .gitignore
    (repo / ".gitignore").write_text("ignored_folder/\n*.secret.py\n", encoding="utf-8")

    (repo / "ignored_folder").mkdir()
    (repo / "ignored_folder" / "secret.py").write_text("@app.get('/secret')\ndef s(): pass", encoding="utf-8")

    (repo / "backend" / "test.secret.py").write_text("@app.get('/secret2')\ndef s2(): pass", encoding="utf-8")

    indexer = IncrementalIndexer(repo_path=repo)
    discovered = indexer.discover_files()
    rel_files = [rel_p for _, rel_p in discovered]

    # Verify standard files discovered
    assert "backend/main.py" in rel_files
    assert "frontend/App.tsx" in rel_files

    # Verify ignored paths are filtered out
    assert not any("node_modules" in f for f in rel_files)
    assert not any(".venv" in f for f in rel_files)
    assert not any("__pycache__" in f for f in rel_files)
    assert not any("ignored_folder" in f for f in rel_files)
    assert not any("test.secret.py" in f for f in rel_files)

    # Verify graph indexing excludes ignored routes
    graph, report = indexer.index(use_cache=False)
    assert graph.node_count == 2
    assert len(graph.frontend_calls) == 1
    assert len(graph.backend_routes) == 1


def test_incremental_cache_lifecycle(tmp_path: Path):
    """Verify SHA-256 caching: full first run, instant cache hit on second run, and selective re-parse on modification."""
    # Create an isolated temporary copy of advanced_fullstack fixture
    test_repo = tmp_path / "advanced_fullstack_copy"
    shutil.copytree(ADVANCED_FIXTURE_DIR, test_repo)

    cache_file = tmp_path / "cache_store.json"
    indexer = IncrementalIndexer(repo_path=test_repo, cache_path=cache_file)

    # Run 1: Cold indexing
    graph1, report1 = indexer.index(use_cache=True)
    assert report1.total_files >= 4
    assert report1.modified_files == report1.total_files
    assert report1.cached_files_hit == 0
    assert graph1.node_count >= 4
    assert cache_file.exists()

    # Run 2: Hot indexing without modifications
    graph2, report2 = indexer.index(use_cache=True)
    assert report2.total_files == report1.total_files
    assert report2.modified_files == 0
    assert report2.cached_files_hit == report1.total_files
    assert report2.duration_ms < 50.0  # High-speed cache hit under 50ms (typically <5ms)
    assert graph2.node_count == graph1.node_count
    assert graph2.edge_count == graph1.edge_count

    # Run 3: Modify one file and verify incremental re-indexing of only 1 file
    auth_file = test_repo / "backend" / "routers" / "auth.py"
    original_content = auth_file.read_text(encoding="utf-8")
    modified_content = original_content + "\n@router.get('/v2/verify')\ndef verify_token(): return {'valid': True}\n"
    auth_file.write_text(modified_content, encoding="utf-8")

    graph3, report3 = indexer.index(use_cache=True)
    assert report3.total_files == report1.total_files
    assert report3.modified_files == 1  # ONLY auth.py re-parsed!
    assert report3.cached_files_hit == report1.total_files - 1
    assert graph3.node_count > graph1.node_count


def test_parallel_ast_parser_multi_file():
    """Verify ParallelASTParser executes concurrent parsing on mixed multi-file inputs."""
    parser = ParallelASTParser(max_workers=4)

    files_to_parse = [
        str(ADVANCED_FIXTURE_DIR / "backend" / "app.py"),
        str(ADVANCED_FIXTURE_DIR / "backend" / "routers" / "analytics.py"),
        str(ADVANCED_FIXTURE_DIR / "backend" / "routers" / "auth.py"),
        str(ADVANCED_FIXTURE_DIR / "frontend" / "Dashboard.tsx"),
        str(SYNTHETIC_FIXTURE_DIR / "backend" / "models.py"),
        str(SYNTHETIC_FIXTURE_DIR / "backend" / "routes.py"),
        str(SYNTHETIC_FIXTURE_DIR / "frontend" / "UserProfile.tsx"),
    ]

    results = parser.parse_files(files_to_parse)

    assert len(results) == len(files_to_parse)

    # Check each file result has valid SHA-256 and AST structures
    for res in results:
        assert "sha256" in res and len(res["sha256"]) == 64
        assert "rel_path" in res
        assert "fe_calls" in res
        assert "routes" in res
        assert "models" in res

    # Verify routes extracted
    all_routes = [r for res in results for r in res["routes"]]
    assert len(all_routes) >= 4

    # Verify models extracted
    all_models = [m for res in results for m in res["models"]]
    assert len(all_models) >= 2
    model_names = [m.class_name for m in all_models]
    assert "User" in model_names
    assert "BillingAccount" in model_names

    # Verify frontend calls extracted
    all_fetches = [f for res in results for f in res["fe_calls"]]
    assert len(all_fetches) >= 3
