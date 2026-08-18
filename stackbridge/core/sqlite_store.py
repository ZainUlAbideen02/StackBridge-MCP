"""SQLite Store with Recursive CTE Blast-Radius Traversal for Enterprise Repositories."""

import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from stackbridge.core.graph import StackGraph
from stackbridge.core.models import (
    BackendRoute,
    EndpointParam,
    FrontendEndpointCall,
    GraphEdge,
    GraphNode,
    HttpMethod,
    ORMField,
    ORMModel,
)


class SQLiteStore:
    """Manages SQLite storage and high-speed recursive CTE graph traversal for enterprise codebases."""

    def __init__(self, db_path: Union[str, Path] = ".stackbridge/graph.db") -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def init_schema(self) -> None:
        """Initializes SQLite tables and indexes for graph nodes, edges, and recursive CTE queries."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    node_type TEXT,
                    file_path TEXT,
                    line_number INTEGER,
                    symbol_name TEXT,
                    is_critical INTEGER DEFAULT 0,
                    properties TEXT
                );

                CREATE TABLE IF NOT EXISTS edges (
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    relation_type TEXT,
                    confidence REAL DEFAULT 1.0,
                    properties TEXT,
                    PRIMARY KEY (source, target, relation)
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
                CREATE INDEX IF NOT EXISTS idx_edges_rel_type ON edges(relation_type);
            """)
            conn.commit()

    def save_graph(self, graph: StackGraph) -> None:
        """Persists the in-memory StackGraph to SQLite."""
        graph_dict = graph.to_dict()
        nodes = graph_dict.get("nodes", [])
        edges = graph_dict.get("edges", [])

        with self._get_connection() as conn:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM edges;")
            conn.execute("DELETE FROM nodes;")

            for n in nodes:
                node_id = n["id"]
                n_type = n.get("type", "unknown")
                node_type = n.get("node_type", n_type)
                file_p = n.get("file_path", "")
                line_no = n.get("line_number") or n.get("line", 1)
                symbol_name = n.get("function_name") or n.get("class_name") or node_id.split("::")[-1]
                is_crit = 1 if n.get("is_critical") else 0
                props_json = json.dumps(n)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO nodes (id, type, node_type, file_path, line_number, symbol_name, is_critical, properties)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (node_id, n_type, node_type, file_p, line_no, symbol_name, is_crit, props_json),
                )

            for e in edges:
                src = e["source"]
                tgt = e["target"]
                rel = e.get("relation", "relates_to")
                rel_type = e.get("relation_type", "ASSOCIATION")
                conf = float(e.get("confidence", 1.0))
                props_json = json.dumps(e)

                conn.execute(
                    """
                    INSERT OR REPLACE INTO edges (source, target, relation, relation_type, confidence, properties)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (src, tgt, rel, rel_type, conf, props_json),
                )

            conn.commit()

    def load_graph(self) -> StackGraph:
        """Constructs a StackGraph from the SQLite store."""
        sg = StackGraph()
        with self._get_connection() as conn:
            rows = conn.execute("SELECT properties FROM nodes").fetchall()
            for r in rows:
                n_dict = json.loads(r["properties"])
                sg.graph.add_node(n_dict["id"], **n_dict)

            edge_rows = conn.execute("SELECT properties FROM edges").fetchall()
            for er in edge_rows:
                e_dict = json.loads(er["properties"])
                src = e_dict["source"]
                tgt = e_dict["target"]
                props = {k: v for k, v in e_dict.items() if k not in ("source", "target")}
                sg.graph.add_edge(src, tgt, **props)

        return sg

    def recursive_cte_blast_radius(self, target_identifier: str, max_depth: int = 8) -> Dict[str, Any]:
        """
        Executes a high-performance SQLite recursive Common Table Expression (CTE) query
        traversing bidirectional dependencies across UI components, API routes, and ORM models.
        """
        clean_target = target_identifier.replace("\\", "/")
        with self._get_connection() as conn:
            # 1. Resolve starting node
            match_row = conn.execute(
                """
                SELECT id, file_path, symbol_name, type FROM nodes
                WHERE id = ? OR id LIKE ? OR symbol_name = ? OR file_path = ?
                LIMIT 1
                """,
                (clean_target, f"%{clean_target}%", clean_target, clean_target),
            ).fetchone()

            if not match_row:
                return {
                    "target": target_identifier,
                    "found": False,
                    "affected_nodes": [],
                    "affected_routes": [],
                    "affected_frontend": [],
                    "affected_files": [],
                    "paths": [],
                    "traversal_engine": "sqlite_recursive_cte",
                }

            start_node_id = match_row["id"]

            # 2. Run Bidirectional Recursive CTE
            query = """
            WITH RECURSIVE blast_cte(node_id, depth, path) AS (
                -- Base Case
                SELECT ?, 0, ?
                UNION
                -- Downstream & Upstream edges
                SELECT 
                    CASE 
                        WHEN e.source = b.node_id THEN e.target 
                        ELSE e.source 
                    END,
                    b.depth + 1,
                    b.path || ' -> ' || CASE WHEN e.source = b.node_id THEN e.target ELSE e.source END
                FROM edges e
                JOIN blast_cte b ON (e.source = b.node_id OR e.target = b.node_id)
                WHERE b.depth < ?
                  AND INSTR(b.path, CASE WHEN e.source = b.node_id THEN e.target ELSE e.source END) = 0
            )
            SELECT DISTINCT b.node_id, b.depth, b.path, n.type, n.node_type, n.file_path, n.symbol_name, n.is_critical, n.properties
            FROM blast_cte b
            JOIN nodes n ON b.node_id = n.id
            ORDER BY b.depth ASC;
            """

            rows = conn.execute(query, (start_node_id, start_node_id, max_depth)).fetchall()

            affected_nodes: List[str] = []
            affected_routes: List[Dict[str, Any]] = []
            affected_frontend: List[Dict[str, Any]] = []
            affected_files: Set[str] = set()
            paths: List[str] = []

            for r in rows:
                nid = r["node_id"]
                ntype = r["type"]
                fpath = r["file_path"]
                path_str = r["path"]
                if fpath:
                    affected_files.add(fpath)

                if nid != start_node_id:
                    affected_nodes.append(nid)
                    paths.append(path_str)

                if ntype in ("route", "api_route"):
                    affected_routes.append({"id": nid, "file_path": fpath, "name": r["symbol_name"]})
                elif ntype in ("frontend", "frontend_component"):
                    affected_frontend.append({"id": nid, "file_path": fpath, "line": r["line_number"] if "line_number" in r.keys() else 1})

            return {
                "target": start_node_id,
                "found": True,
                "affected_nodes": affected_nodes,
                "affected_routes": affected_routes,
                "affected_frontend": affected_frontend,
                "affected_files": sorted(list(affected_files)),
                "paths": paths,
                "traversal_engine": "sqlite_recursive_cte",
            }
