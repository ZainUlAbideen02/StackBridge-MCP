"""Configuration and Business Criticality Rules for StackBridge-MCP."""

import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigSchema(BaseModel):
    critical_paths: List[str] = Field(default_factory=lambda: ["auth/**", "billing/**", "payments/**", "*auth*", "*billing*", "*payment*"])
    ignored_paths: List[str] = Field(default_factory=lambda: ["**/*.tmp", "**/*.cache"])
    criticality_weight_boost: float = 2.5


class StackBridgeConfig:
    """Loads and evaluates business criticality rules and custom path configurations."""

    def __init__(self, repo_path: Union[str, Path] = ".") -> None:
        self.repo_dir = Path(repo_path).resolve()
        self.config_data = self._load_config_file()

    def _load_config_file(self) -> ConfigSchema:
        config_candidates = [
            self.repo_dir / "stackbridge.yaml",
            self.repo_dir / "stackbridge.yml",
            self.repo_dir / ".stackbridge.yaml",
            self.repo_dir / ".stackbridge.yml",
        ]

        for candidate in config_candidates:
            if candidate.exists():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        if HAS_YAML and yaml:
                            parsed = yaml.safe_load(f) or {}
                        else:
                            # Basic line parser fallback if pyyaml is unavailable
                            parsed = self._simple_yaml_fallback(f.read())
                    return ConfigSchema(**parsed)
                except Exception:
                    pass

        return ConfigSchema()

    def _simple_yaml_fallback(self, content: str) -> Dict[str, Any]:
        """Simple YAML fallback parser for basic lists."""
        data: Dict[str, Any] = {}
        current_key = None
        for line in content.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            if ":" in line_str and not line_str.startswith("-"):
                k, v = line_str.split(":", 1)
                current_key = k.strip()
                v_clean = v.strip().strip("[]")
                if v_clean:
                    data[current_key] = [item.strip().strip("'\"") for item in v_clean.split(",") if item.strip()]
                else:
                    data[current_key] = []
            elif line_str.startswith("-") and current_key:
                val = line_str.lstrip("-").strip().strip("'\"")
                if current_key not in data:
                    data[current_key] = []
                data[current_key].append(val)
        return data

    @property
    def critical_paths(self) -> List[str]:
        return self.config_data.critical_paths

    @property
    def ignored_paths(self) -> List[str]:
        return self.config_data.ignored_paths

    @property
    def criticality_weight_boost(self) -> float:
        return self.config_data.criticality_weight_boost

    def is_critical_path(self, file_path: Union[str, Path]) -> bool:
        """Determines if a file path matches any business-critical path pattern."""
        p_str = Path(file_path).as_posix().lstrip("/")
        parts = p_str.split("/")

        for pat in self.critical_paths:
            pat_clean = pat.replace("\\", "/").strip("/")
            if fnmatch.fnmatch(p_str, pat_clean) or fnmatch.fnmatch(p_str, f"*/{pat_clean}") or fnmatch.fnmatch(p_str, f"**/{pat_clean}"):
                return True
            if any(fnmatch.fnmatch(part, pat_clean) for part in parts):
                return True
            if pat_clean.strip("*") and pat_clean.strip("*") in p_str:
                return True

        return False

    def is_ignored_path(self, file_path: Union[str, Path]) -> bool:
        """Determines if a file path matches custom ignored path patterns."""
        p_str = Path(file_path).as_posix().lstrip("/")
        for pat in self.ignored_paths:
            pat_clean = pat.replace("\\", "/").strip("/")
            if fnmatch.fnmatch(p_str, pat_clean) or fnmatch.fnmatch(p_str, f"*/{pat_clean}"):
                return True
        return False

    def tag_graph_nodes(self, graph: Any) -> None:
        """Tags matching graph nodes with is_critical: True."""
        for node_id, data in graph.graph.nodes(data=True):
            file_p = data.get("file_path", "")
            if file_p and self.is_critical_path(file_p):
                data["is_critical"] = True
                data["criticality_weight"] = self.criticality_weight_boost
            else:
                data.setdefault("is_critical", False)
                data.setdefault("criticality_weight", 1.0)
