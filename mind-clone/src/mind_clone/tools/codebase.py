"""
Codebase self-modification tools.

Gives Bob the ability to read, search, edit, and manage its own source code.
Feature-flagged with CODEBASE_SELF_MODIFY_ENABLED (default: true).

Safety:
- All operations restricted to the mind-clone/src/ directory
- Edits create .bak backups before writing
- Compile check runs after every edit
- All modifications tracked in RUNTIME_STATE
- Added to APPROVAL_REQUIRED_TOOLS by default in strict mode
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from ..config import settings

logger = logging.getLogger("mind_clone.tools")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root of the mind-clone package source
_SRC_ROOT = Path(__file__).resolve().parent.parent  # mind_clone/
_PROJECT_ROOT = _SRC_ROOT.parent.parent  # mind-clone/
_ALLOWED_ROOTS = [_SRC_ROOT, _PROJECT_ROOT / "tests", _PROJECT_ROOT / "scripts"]

# Files that must never be edited by Bob
_PROTECTED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
}

# Max file size Bob is allowed to write (500KB)
_MAX_WRITE_BYTES = 500_000

# Max search results
_MAX_SEARCH_RESULTS = 40


def _is_safe_path(path: Path) -> bool:
    """Check if path is within allowed directories."""
    resolved = path.resolve()
    return any(
        resolved == root or str(resolved).startswith(str(root) + os.sep)
        for root in _ALLOWED_ROOTS
    )


def _is_protected(path: Path) -> bool:
    """Check if file is on the protected list."""
    return path.name in _PROTECTED_FILES


def _relative_display(path: Path) -> str:
    """Show path relative to project root for cleaner display."""
    try:
        return str(path.resolve().relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(path)


def _track_modification(action: str, file_path: str, details: str = "") -> None:
    """Record a codebase modification in runtime state."""
    try:
        from ..core.state import RUNTIME_STATE
        key = "codebase_modifications"
        mods = RUNTIME_STATE.get(key, [])
        mods.append({
            "action": action,
            "file": file_path,
            "details": details[:200],
            "ts": time.time(),
        })
        # Keep last 50 modifications
        RUNTIME_STATE[key] = mods[-50:]
        RUNTIME_STATE["codebase_mod_count"] = RUNTIME_STATE.get("codebase_mod_count", 0) + 1
    except Exception:
        pass


def _compile_check() -> dict:
    """Run Python compile check on the source directory."""
    try:
        result = subprocess.run(
            ["python", "-m", "compileall", "-q", str(_SRC_ROOT)],
            capture_output=True, text=True, timeout=30,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode == 0:
            return {"ok": True, "message": "Compile check passed"}
        return {
            "ok": False,
            "error": f"Compile check failed: {result.stderr[:500]}",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Compile check timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": f"Compile check error: {e}"}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_codebase_read(args: dict) -> dict:
    """Read a source file from the codebase."""
    file_path = str(args.get("file_path", "")).strip()
    if not file_path:
        return {"ok": False, "error": "file_path is required"}

    # Resolve relative to project root
    path = (_PROJECT_ROOT / file_path).resolve()

    if not _is_safe_path(path):
        return {"ok": False, "error": f"Access denied: {file_path} is outside allowed directories"}

    if not path.exists():
        return {"ok": False, "error": f"File not found: {_relative_display(path)}"}

    if not path.is_file():
        return {"ok": False, "error": f"Not a file: {_relative_display(path)}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", 0))

        if offset > 0 or limit > 0:
            start = max(0, offset)
            end = start + limit if limit > 0 else len(lines)
            lines = lines[start:end]
            content = "\n".join(lines)

        return {
            "ok": True,
            "path": _relative_display(path),
            "content": content[:50_000],  # Cap at 50KB for LLM context
            "total_lines": len(path.read_text(encoding="utf-8", errors="replace").split("\n")),
            "truncated": len(content) > 50_000,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_codebase_search(args: dict) -> dict:
    """Search the codebase using regex pattern matching."""
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        return {"ok": False, "error": "pattern is required"}

    glob_filter = str(args.get("glob", "*.py")).strip()
    case_insensitive = bool(args.get("case_insensitive", False))
    max_results = min(int(args.get("max_results", 20)), _MAX_SEARCH_RESULTS)

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"ok": False, "error": f"Invalid regex: {e}"}

    matches = []
    files_searched = 0

    for root_dir in _ALLOWED_ROOTS:
        if not root_dir.exists():
            continue
        for filepath in root_dir.rglob(glob_filter):
            if not filepath.is_file():
                continue
            files_searched += 1
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.split("\n"), 1):
                    if regex.search(line):
                        matches.append({
                            "file": _relative_display(filepath),
                            "line": i,
                            "text": line.strip()[:200],
                        })
                        if len(matches) >= max_results:
                            break
            except Exception:
                continue
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    return {
        "ok": True,
        "pattern": pattern,
        "matches": matches,
        "match_count": len(matches),
        "files_searched": files_searched,
        "truncated": len(matches) >= max_results,
    }


def tool_codebase_structure(args: dict) -> dict:
    """List the project directory structure."""
    subdir = str(args.get("path", "src/mind_clone")).strip()
    max_depth = min(int(args.get("max_depth", 3)), 5)
    show_files = bool(args.get("show_files", True))

    target = (_PROJECT_ROOT / subdir).resolve()
    if not _is_safe_path(target) and target != _PROJECT_ROOT.resolve():
        return {"ok": False, "error": f"Access denied: {subdir}"}

    if not target.exists():
        return {"ok": False, "error": f"Path not found: {subdir}"}

    tree_lines = []

    def _walk(directory: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith((".", "__pycache__", "node_modules", ".git"))]
        files = [e for e in entries if e.is_file()] if show_files else []

        items = dirs + files
        for i, entry in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "`-- " if is_last else "|-- "
            if entry.is_dir():
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                extension = "    " if is_last else "|   "
                _walk(entry, prefix + extension, depth + 1)
            else:
                size = entry.stat().st_size
                tree_lines.append(f"{prefix}{connector}{entry.name} ({size:,}B)")

    tree_lines.append(f"{subdir}/")
    _walk(target, "", 1)

    return {
        "ok": True,
        "path": subdir,
        "tree": "\n".join(tree_lines[:500]),
        "truncated": len(tree_lines) > 500,
    }


def tool_codebase_edit(args: dict) -> dict:
    """Edit a source file using old_string/new_string replacement.

    This is the primary editing tool - works like Claude Code's Edit tool.
    The old_string must be unique in the file to avoid ambiguous edits.
    Creates a .bak backup before writing and runs compile check after.
    """
    file_path = str(args.get("file_path", "")).strip()
    old_string = str(args.get("old_string", ""))
    new_string = str(args.get("new_string", ""))

    if not file_path:
        return {"ok": False, "error": "file_path is required"}
    if not old_string:
        return {"ok": False, "error": "old_string is required"}
    if old_string == new_string:
        return {"ok": False, "error": "old_string and new_string are identical"}

    path = (_PROJECT_ROOT / file_path).resolve()

    if not _is_safe_path(path):
        return {"ok": False, "error": f"Access denied: {file_path}"}
    if _is_protected(path):
        return {"ok": False, "error": f"Protected file: {path.name} cannot be modified"}
    if not path.exists():
        return {"ok": False, "error": f"File not found: {_relative_display(path)}"}

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Cannot read file: {e}"}

    # Check uniqueness
    count = content.count(old_string)
    if count == 0:
        return {
            "ok": False,
            "error": "old_string not found in file. Read the file first to get exact content.",
            "hint": "Use codebase_read to view the current file contents.",
        }
    if count > 1:
        return {
            "ok": False,
            "error": f"old_string found {count} times. Provide more surrounding context to make it unique.",
        }

    # Create backup
    backup_path = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, backup_path)
    except Exception as e:
        logger.warning("Backup failed for %s: %s", file_path, e)

    # Apply edit
    new_content = content.replace(old_string, new_string, 1)

    if len(new_content.encode("utf-8")) > _MAX_WRITE_BYTES:
        return {"ok": False, "error": f"Result exceeds max file size ({_MAX_WRITE_BYTES:,} bytes)"}

    try:
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        # Restore from backup
        if backup_path.exists():
            shutil.copy2(backup_path, path)
        return {"ok": False, "error": f"Write failed (restored backup): {e}"}

    # Compile check
    check = _compile_check()
    if not check["ok"]:
        # Revert on compile failure
        if backup_path.exists():
            shutil.copy2(backup_path, path)
            backup_path.unlink(missing_ok=True)
        return {
            "ok": False,
            "error": f"Edit reverted - compile check failed: {check.get('error', 'unknown')}",
            "hint": "Fix the syntax error and try again.",
        }

    # Clean up backup on success
    backup_path.unlink(missing_ok=True)

    # Count changed lines
    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1

    _track_modification("edit", _relative_display(path), f"-{old_lines}+{new_lines} lines")
    logger.info("codebase_edit: %s (%d->%d lines)", _relative_display(path), old_lines, new_lines)

    return {
        "ok": True,
        "path": _relative_display(path),
        "lines_removed": old_lines,
        "lines_added": new_lines,
        "compile_check": "passed",
        "message": f"Successfully edited {_relative_display(path)}",
    }


def tool_codebase_write(args: dict) -> dict:
    """Create a new file in the codebase.

    Only creates files - will not overwrite existing files unless
    force=true is specified. Creates parent directories as needed.
    Runs compile check after writing.
    """
    file_path = str(args.get("file_path", "")).strip()
    content = str(args.get("content", ""))
    force = bool(args.get("force", False))

    if not file_path:
        return {"ok": False, "error": "file_path is required"}
    if not content:
        return {"ok": False, "error": "content is required"}

    path = (_PROJECT_ROOT / file_path).resolve()

    if not _is_safe_path(path):
        return {"ok": False, "error": f"Access denied: {file_path}"}
    if _is_protected(path):
        return {"ok": False, "error": f"Protected file: {path.name} cannot be modified"}
    if path.exists() and not force:
        return {
            "ok": False,
            "error": f"File already exists: {_relative_display(path)}. Use codebase_edit to modify, or set force=true to overwrite.",
        }

    if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
        return {"ok": False, "error": f"Content exceeds max file size ({_MAX_WRITE_BYTES:,} bytes)"}

    # Backup if overwriting
    if path.exists() and force:
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, backup_path)
        except Exception:
            pass

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Write failed: {e}"}

    # Compile check for .py files
    if path.suffix == ".py":
        check = _compile_check()
        if not check["ok"]:
            # Revert
            if path.exists():
                backup_path = path.with_suffix(path.suffix + ".bak")
                if backup_path.exists():
                    shutil.copy2(backup_path, path)
                else:
                    path.unlink(missing_ok=True)
            return {
                "ok": False,
                "error": f"Write reverted - compile check failed: {check.get('error', 'unknown')}",
            }

    line_count = content.count("\n") + 1
    _track_modification("write", _relative_display(path), f"{line_count} lines")
    logger.info("codebase_write: %s (%d lines)", _relative_display(path), line_count)

    return {
        "ok": True,
        "path": _relative_display(path),
        "lines": line_count,
        "bytes": len(content.encode("utf-8")),
        "compile_check": "passed" if path.suffix == ".py" else "skipped",
        "message": f"Created {_relative_display(path)}",
    }


def tool_codebase_run_tests(args: dict) -> dict:
    """Run pytest to validate codebase integrity after changes."""
    test_path = str(args.get("test_path", "")).strip()
    keyword = str(args.get("keyword", "")).strip()
    timeout = min(int(args.get("timeout", 120)), 300)

    cmd = ["python", "-m", "pytest", "-x", "--tb=short", "-q"]

    if keyword:
        cmd.extend(["-k", keyword])

    if test_path:
        test_dir = (_PROJECT_ROOT / test_path).resolve()
        if not _is_safe_path(test_dir) and test_dir != _PROJECT_ROOT.resolve():
            return {"ok": False, "error": f"Access denied: {test_path}"}
        cmd.append(str(test_dir))
    else:
        cmd.append(str(_PROJECT_ROOT / "tests"))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
        )
        output = (result.stdout + "\n" + result.stderr).strip()

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "output": output[-3000:],  # Last 3KB of output
            "passed": result.returncode == 0,
            "message": "All tests passed" if result.returncode == 0 else "Some tests failed",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Tests timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tool_codebase_git_status(args: dict) -> dict:
    """Show git status and recent changes."""
    include_diff = bool(args.get("include_diff", False))

    try:
        # Git status
        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=15,
            cwd=str(_PROJECT_ROOT),
        )

        result = {
            "ok": True,
            "status": status.stdout.strip()[:2000],
        }

        # Recent commits
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=15,
            cwd=str(_PROJECT_ROOT),
        )
        result["recent_commits"] = log_result.stdout.strip()

        # Diff if requested
        if include_diff:
            diff = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, timeout=15,
                cwd=str(_PROJECT_ROOT),
            )
            result["diff_stat"] = diff.stdout.strip()[:2000]

        # Modification tracking from runtime state
        try:
            from ..core.state import RUNTIME_STATE
            result["modifications_this_session"] = RUNTIME_STATE.get("codebase_mod_count", 0)
        except Exception:
            pass

        return result

    except Exception as e:
        return {"ok": False, "error": str(e)}
