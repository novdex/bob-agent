"""
Persistent codebase knowledge base (DeepWiki-style).

Auto-indexes project structure, key symbols, dependencies, and patterns
for instant retrieval in future sessions.

Pillar: Memory, World Understanding
"""

from __future__ import annotations

import ast
import json
import logging
import os
import pathlib
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mind_clone.core.knowledge")

# Directories to skip during scan
_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", "dist", "build", "venv",
    ".venv", ".env", "persist", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "egg-info", ".eggs", "htmlcov",
})

# File extensions to index
_INDEX_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".md", ".rst", ".txt", ".sh", ".ps1",
    ".dockerfile", ".sql", ".html", ".css",
})

# In-memory cache: root_path -> CodebaseIndex
_INDEX_CACHE: Dict[str, "CodebaseIndex"] = {}


def _text_similarity(text1: str, text2: str) -> float:
    """Jaccard word-overlap similarity between two texts."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / len(words1 | words2)


# ---------------------------------------------------------------------------
# Python AST extraction
# ---------------------------------------------------------------------------

def extract_python_symbols(file_path: str) -> Dict[str, Any]:
    """Extract classes, functions, imports from a Python file using AST.

    Returns dict with keys: classes, functions, imports, docstring.
    Handles SyntaxError gracefully.
    """
    result: Dict[str, Any] = {
        "classes": [], "functions": [], "imports": [], "docstring": "",
    }
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return result
    except Exception:
        return result

    # Module docstring
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Str, ast.Constant))):
        val = tree.body[0].value
        result["docstring"] = getattr(val, "s", str(getattr(val, "value", "")))[:200]

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            result["classes"].append({"name": node.name, "methods": methods[:20], "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip methods (already captured in classes)
            if not isinstance(getattr(node, "_parent", None), ast.ClassDef):
                result["functions"].append({"name": node.name, "line": node.lineno})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            result["imports"].append(module)

    # Limit sizes
    result["functions"] = result["functions"][:50]
    result["imports"] = result["imports"][:50]
    return result


# ---------------------------------------------------------------------------
# CodebaseIndex
# ---------------------------------------------------------------------------

class CodebaseIndex:
    """Persistent index of a project's structure and symbols."""

    def __init__(self, root_path: str):
        self.root_path = str(pathlib.Path(root_path).resolve())
        self.project_name = pathlib.Path(self.root_path).name
        self.files: List[Dict[str, Any]] = []
        self.symbols: Dict[str, Dict] = {}  # path -> symbols
        self.dependencies: Dict[str, List[str]] = {}
        self.entry_points: List[str] = []
        self.config_files: List[str] = []
        self.languages: Dict[str, int] = {}
        self.scan_time: float = 0
        self.total_lines: int = 0

    def scan(self) -> Dict[str, Any]:
        """Scan the project tree and build the index."""
        t0 = time.monotonic()
        root = pathlib.Path(self.root_path)
        if not root.is_dir():
            return {"ok": False, "error": f"Not a directory: {self.root_path}"}

        self.files = []
        self.symbols = {}
        self.languages = {}
        self.total_lines = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Skip excluded directories
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]

            for fname in filenames:
                fpath = pathlib.Path(dirpath) / fname
                ext = fpath.suffix.lower()
                if ext not in _INDEX_EXTENSIONS:
                    continue

                rel_path = str(fpath.relative_to(root))
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue

                # Count lines
                lines = 0
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        lines = sum(1 for _ in f)
                except Exception:
                    pass

                self.total_lines += lines
                lang = self._ext_to_language(ext)
                self.languages[lang] = self.languages.get(lang, 0) + 1

                file_info: Dict[str, Any] = {
                    "path": rel_path,
                    "size": size,
                    "lines": lines,
                    "language": lang,
                    "extension": ext,
                }
                self.files.append(file_info)

                # Python AST extraction
                if ext == ".py":
                    symbols = extract_python_symbols(str(fpath))
                    if symbols["classes"] or symbols["functions"]:
                        self.symbols[rel_path] = symbols

                # Detect special files
                lower_name = fname.lower()
                if lower_name in ("requirements.txt", "package.json", "pyproject.toml",
                                  "cargo.toml", "go.mod", "pom.xml"):
                    self._parse_deps(str(fpath), lower_name)
                if lower_name in ("main.py", "__main__.py", "app.py", "server.py",
                                  "index.js", "index.ts", "manage.py"):
                    self.entry_points.append(rel_path)
                if lower_name in (".env.example", "docker-compose.yml", "dockerfile",
                                  "makefile", ".gitignore", "tsconfig.json", "vite.config.ts"):
                    self.config_files.append(rel_path)

        self.scan_time = time.monotonic() - t0
        logger.info("CODEBASE_INDEXED project=%s files=%d symbols=%d time=%.1fs",
                     self.project_name, len(self.files), len(self.symbols), self.scan_time)

        # Cache
        _INDEX_CACHE[self.root_path] = self
        return {"ok": True, "files": len(self.files), "symbols": len(self.symbols)}

    def query(self, question: str) -> List[str]:
        """Search the index for information relevant to a question."""
        results: List[tuple] = []  # (score, text)

        for file_info in self.files:
            score = _text_similarity(question, file_info["path"])
            if score > 0.05:
                results.append((score, f"File: {file_info['path']} ({file_info['lines']} lines, {file_info['language']})"))

        for path, syms in self.symbols.items():
            # Search classes
            for cls in syms.get("classes", []):
                text = f"Class {cls['name']} in {path} (methods: {', '.join(cls['methods'][:5])})"
                score = _text_similarity(question, text)
                if score > 0.05:
                    results.append((score, text))
            # Search functions
            for func in syms.get("functions", []):
                text = f"Function {func['name']} in {path}"
                score = _text_similarity(question, text)
                if score > 0.05:
                    results.append((score, text))
            # Search docstrings
            if syms.get("docstring"):
                score = _text_similarity(question, syms["docstring"])
                if score > 0.1:
                    results.append((score, f"{path}: {syms['docstring'][:100]}"))

        results.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in results[:20]]

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level project summary."""
        return {
            "project_name": self.project_name,
            "root_path": self.root_path,
            "total_files": len(self.files),
            "total_lines": self.total_lines,
            "languages": dict(sorted(self.languages.items(), key=lambda x: -x[1])),
            "python_symbols": len(self.symbols),
            "entry_points": self.entry_points[:10],
            "config_files": self.config_files[:10],
            "dependencies": {k: v[:10] for k, v in self.dependencies.items()},
            "scan_time_seconds": round(self.scan_time, 2),
        }

    def save(self, path: Optional[str] = None) -> str:
        """Save index to JSON file."""
        if path is None:
            persist_dir = pathlib.Path("persist/knowledge")
            persist_dir.mkdir(parents=True, exist_ok=True)
            path = str(persist_dir / f"{self.project_name}_index.json")

        data = {
            "root_path": self.root_path,
            "project_name": self.project_name,
            "files": self.files,
            "symbols": self.symbols,
            "dependencies": self.dependencies,
            "entry_points": self.entry_points,
            "config_files": self.config_files,
            "languages": self.languages,
            "total_lines": self.total_lines,
            "scan_time": self.scan_time,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("KNOWLEDGE_SAVED path=%s", path)
        return path

    def load(self, path: str) -> bool:
        """Load index from JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.root_path = data.get("root_path", self.root_path)
            self.project_name = data.get("project_name", self.project_name)
            self.files = data.get("files", [])
            self.symbols = data.get("symbols", {})
            self.dependencies = data.get("dependencies", {})
            self.entry_points = data.get("entry_points", [])
            self.config_files = data.get("config_files", [])
            self.languages = data.get("languages", {})
            self.total_lines = data.get("total_lines", 0)
            self.scan_time = data.get("scan_time", 0)
            _INDEX_CACHE[self.root_path] = self
            return True
        except Exception as exc:
            logger.warning("KNOWLEDGE_LOAD_FAIL path=%s error=%s", path, str(exc)[:200])
            return False

    def _parse_deps(self, file_path: str, filename: str) -> None:
        """Parse dependency files."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if filename == "requirements.txt":
                deps = [line.split("==")[0].split(">=")[0].strip()
                        for line in content.splitlines()
                        if line.strip() and not line.startswith("#")]
                self.dependencies["python"] = deps[:50]
            elif filename == "package.json":
                pkg = json.loads(content)
                deps = list(pkg.get("dependencies", {}).keys())
                deps += list(pkg.get("devDependencies", {}).keys())
                self.dependencies["node"] = deps[:50]
            elif filename == "pyproject.toml":
                # Simple extraction (no toml parser needed)
                self.dependencies.setdefault("python_project", [filename])
        except Exception:
            pass

    @staticmethod
    def _ext_to_language(ext: str) -> str:
        """Map file extension to language name."""
        return {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".tsx": "TypeScript/React", ".jsx": "JavaScript/React",
            ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
            ".toml": "TOML", ".md": "Markdown", ".html": "HTML",
            ".css": "CSS", ".sql": "SQL", ".sh": "Shell",
            ".ps1": "PowerShell", ".dockerfile": "Docker",
        }.get(ext, ext)
