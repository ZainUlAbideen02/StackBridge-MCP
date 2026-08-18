"""Continuous Background File Watcher and Graph Warmer for StackBridge-MCP."""

import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Union

from stackbridge.core.git_delta import GitDeltaIndexer
from stackbridge.core.graph import StackGraph

try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


class DebouncedChangeHandler:
    """Collects and batches file modification events over a debounce window (300ms)."""

    def __init__(self, debounce_sec: float = 0.3, callback: Optional[Callable[[List[str]], None]] = None) -> None:
        self.debounce_sec = debounce_sec
        self.callback = callback
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._pending_files: Set[str] = set()

    def add_change(self, file_path: str) -> None:
        norm_p = file_path.replace("\\", "/").strip("/")
        ext = os.path.splitext(norm_p)[1].lower()
        if ext not in (".ts", ".tsx", ".js", ".jsx", ".py"):
            return

        with self._lock:
            self._pending_files.add(norm_p)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_sec, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            files_to_process = list(self._pending_files)
            self._pending_files.clear()
            self._timer = None

        if files_to_process and self.callback:
            try:
                self.callback(files_to_process)
            except Exception:
                pass


class BackgroundWatcher:
    """Monitors repository filesystem changes and keeps .stackbridge/graph.db continuously warm."""

    def __init__(
        self,
        repo_path: Union[str, Path] = ".",
        debounce_ms: int = 300,
        on_update_callback: Optional[Callable[[StackGraph], None]] = None,
    ) -> None:
        self.repo_dir = Path(repo_path).resolve()
        self.debounce_sec = debounce_ms / 1000.0
        self.on_update_callback = on_update_callback
        self.git_delta = GitDeltaIndexer(self.repo_dir)

        self._handler = DebouncedChangeHandler(debounce_sec=self.debounce_sec, callback=self._handle_debounced_batch)
        self._running = False
        self._observer = None
        self._poll_thread = None

    def is_running(self) -> bool:
        return self._running

    def _handle_debounced_batch(self, changed_files: List[str]) -> None:
        """Processes debounced batch of modified files and updates SQLite store."""
        try:
            updated_graph = self.git_delta.process_changes(changed_files=changed_files)
            if self.on_update_callback:
                self.on_update_callback(updated_graph)
        except Exception:
            pass

    def start(self) -> None:
        """Starts background file monitoring daemon."""
        if self._running:
            return

        self._running = True

        if HAS_WATCHDOG:
            try:
                class _WatchdogProxy(FileSystemEventHandler):
                    def __init__(self, debouncer: DebouncedChangeHandler):
                        self.debouncer = debouncer

                    def on_modified(self, event: Any):
                        if not event.is_directory:
                            self.debouncer.add_change(event.src_path)

                    def on_created(self, event: Any):
                        if not event.is_directory:
                            self.debouncer.add_change(event.src_path)

                self._observer = Observer()
                self._observer.schedule(_WatchdogProxy(self._handler), str(self.repo_dir), recursive=True)
                self._observer.daemon = True
                self._observer.start()
                return
            except Exception:
                self._observer = None

        # Polling fallback thread
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Lightweight timestamp polling fallback loop."""
        file_mtimes: Dict[str, float] = {}

        while self._running:
            try:
                changed = []
                for root, dirs, files in os.walk(self.repo_dir):
                    dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv", "__pycache__", ".stackbridge", "dist", "build")]
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in (".ts", ".tsx", ".js", ".jsx", ".py"):
                            full_p = os.path.join(root, f)
                            try:
                                mtime = os.path.getmtime(full_p)
                                rel_p = os.path.relpath(full_p, self.repo_dir).replace("\\", "/")
                                if rel_p in file_mtimes and file_mtimes[rel_p] != mtime:
                                    changed.append(rel_p)
                                file_mtimes[rel_p] = mtime
                            except Exception:
                                pass

                for c in changed:
                    self._handler.add_change(c)

            except Exception:
                pass

            time.sleep(self.debounce_sec)

    def stop(self) -> None:
        """Stops background file monitoring cleanly."""
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None
