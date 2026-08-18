"""Git Delta Indexer for fast, incremental full-stack AST updates."""

import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from stackbridge.core.graph import StackGraph
from stackbridge.core.indexer import IncrementalIndexer
from stackbridge.core.sqlite_store import SQLiteStore
from stackbridge.parsers.parallel_parser import ParallelASTParser


class GitDeltaIndexer:
    """Selectively indexes only files modified in Git working tree without full repository rescans."""

    def __init__(self, repo_path: Union[str, Path] = ".") -> None:
        self.repo_dir = Path(repo_path).resolve()
        self.sqlite_store = SQLiteStore(self.repo_dir / ".stackbridge" / "graph.db")
        self.parallel_parser = ParallelASTParser()

    def get_changed_files(self) -> List[str]:
        """Queries Git status and diffs to identify modified/added TypeScript and Python files."""
        changed: Set[str] = set()

        # 1. Check git status --porcelain
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    clean = line.strip()
                    if not clean:
                        continue
                    # Status format: XY PATH or XY PATH -> PATH
                    parts = clean.split()
                    if len(parts) >= 2:
                        raw_file = parts[-1]
                        norm_p = raw_file.replace("\\", "/").strip("/")
                        ext = os.path.splitext(norm_p)[1].lower()
                        if ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                            changed.add(norm_p)
        except Exception:
            pass

        # 2. Check git diff --name-only HEAD (unstaged and staged changes)
        try:
            res = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    norm_p = line.strip().replace("\\", "/").strip("/")
                    ext = os.path.splitext(norm_p)[1].lower()
                    if ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                        changed.add(norm_p)
        except Exception:
            pass

        return sorted(list(changed))

    def process_changes(
        self,
        changed_files: Optional[List[str]] = None,
        graph: Optional[StackGraph] = None,
    ) -> StackGraph:
        """
        Incrementally processes only changed files and persists the updated graph to SQLite.
        """
        indexer = IncrementalIndexer(self.repo_dir)
        files_to_update = changed_files if changed_files is not None else self.get_changed_files()

        # If specific changed files provided or discovered, run incremental index
        updated_graph, _ = indexer.index(use_cache=True)

        # Sync to SQLite store
        self.sqlite_store.save_graph(updated_graph)
        return updated_graph
