#!/usr/bin/env python3
"""bob-find: Navigate the modular package by section/module name.

Usage:
    python bob_find.py                  # List all modules
    python bob_find.py registry         # Show first 50 lines of registry module
    python bob_find.py reg              # Fuzzy match: "reg" -> "registry"
    python bob_find.py llm --lines 100  # Show first 100 lines
    python bob_find.py tools --full     # Show entire module
"""

import argparse
import os
import re
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
MODULAR_DIR = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")

DEFAULT_LINES = 50

# Map short keys to module paths (relative to src/mind_clone/)
MODULE_MAP = {
    "config":    ("config.py",                   "Configuration & env vars"),
    "models":    ("database/models.py",          "Database models (SQLAlchemy)"),
    "tools":     ("tools/",                      "Tool implementations"),
    "registry":  ("tools/registry.py",           "Tool registry (TOOL_DISPATCH)"),
    "schemas":   ("tools/schemas.py",            "Tool schemas (TOOL_DEFINITIONS)"),
    "files":     ("tools/files.py",              "File tools"),
    "web":       ("tools/web.py",                "Web tools"),
    "code":      ("tools/code.py",               "Code tools"),
    "email":     ("tools/email.py",              "Email tools"),
    "desktop":   ("tools/desktop.py",            "Desktop tools"),
    "glove":     ("tools/vector_memory.py",      "GloVe vector memory / semantic search"),
    "identity":  ("agent/identity.py",           "Identity loader"),
    "llm":       ("agent/llm.py",                "LLM client (failover chain)"),
    "loop":      ("agent/loop.py",               "Agent reasoning loop"),
    "memory":    ("agent/memory.py",             "Conversation memory"),
    "reflection":("agent/reflection.py",         "In-loop reflection"),
    "state":     ("core/state.py",               "RUNTIME_STATE + globals"),
    "security":  ("core/security.py",            "Security, policies, approval gate"),
    "budget":    ("core/budget.py",              "Budget governor"),
    "queue":     ("core/queue.py",               "Command queue"),
    "sandbox":   ("core/sandbox.py",             "Execution sandbox"),
    "plugins":   ("core/plugins.py",             "Plugin system"),
    "breaker":   ("core/circuit_breaker.py",     "Circuit breaker"),
    "factory":   ("api/factory.py",              "FastAPI app factory"),
    "routes":    ("api/routes.py",               "API routes (main)"),
    "chat":      ("api/routes/chat.py",          "Chat API routes"),
    "runtime":   ("api/routes/runtime.py",       "Runtime/status API routes"),
    "tasks":     ("services/task_engine.py",     "Task engine"),
    "scheduler": ("services/scheduler.py",       "Scheduler / cron"),
    "telegram":  ("services/telegram.py",        "Telegram adapter"),
    "entry":     ("__main__.py",                 "Entry point"),
}


def discover_modules():
    """Discover all .py files in the modular package and return (key, relpath, title, line_count) list."""
    modules = []
    # First add known modules from MODULE_MAP
    for key, (relpath, title) in MODULE_MAP.items():
        full = os.path.join(MODULAR_DIR, relpath.replace("/", os.sep))
        if os.path.isfile(full):
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
            modules.append((key, relpath, title, line_count))
        elif os.path.isdir(full):
            # For directory entries, count all .py files
            total = 0
            for root, _dirs, fnames in os.walk(full):
                for fn in fnames:
                    if fn.endswith(".py"):
                        fp = os.path.join(root, fn)
                        with open(fp, "r", encoding="utf-8", errors="replace") as f:
                            total += sum(1 for _ in f)
            modules.append((key, relpath, title, total))
    return modules


def fuzzy_match(query, modules):
    """Find modules matching a fuzzy query."""
    query_lower = query.lower()
    matches = []
    for key, relpath, title, lines in modules:
        if query_lower == key:
            matches.append((key, relpath, title, lines))
        elif query_lower in key or query_lower in title.lower() or query_lower in relpath.lower():
            matches.append((key, relpath, title, lines))
    return matches


def main():
    parser = argparse.ArgumentParser(description="Navigate the Bob modular package by module")
    parser.add_argument("section", nargs="?", help="Module name or fuzzy query")
    parser.add_argument("--lines", "-n", type=int, default=DEFAULT_LINES, help="Lines to show (default 50)")
    parser.add_argument("--full", "-f", action="store_true", help="Show entire module")
    args = parser.parse_args()

    if not os.path.isdir(MODULAR_DIR):
        print(f"Error: Modular package not found at {MODULAR_DIR}")
        sys.exit(1)

    modules = discover_modules()

    # List mode
    if not args.section:
        total_lines = sum(lc for _, _, _, lc in modules)
        print(f"Bob Modular Package: {total_lines:,} lines, {len(modules)} modules")
        print(f"  Path: {MODULAR_DIR}")
        print("=" * 70)
        print(f"  {'Key':<12} {'Lines':>6}  {'Path':<30s}  Description")
        print("-" * 70)
        for key, relpath, title, lc in modules:
            print(f"  {key:<12} {lc:>6}  {relpath:<30s}  {title}")
        print()
        print("Usage: python bob_find.py <key>  (e.g., 'registry', 'llm', 'tools')")
        sys.exit(0)

    # Find mode
    matches = fuzzy_match(args.section, modules)
    if not matches:
        print(f"No module matching '{args.section}'")
        print("Available keys:", ", ".join(k for k, _, _, _ in modules))
        sys.exit(1)

    if len(matches) > 1 and not any(m[0] == args.section.lower() for m in matches):
        print(f"Multiple matches for '{args.section}':")
        for key, relpath, title, lc in matches:
            print(f"  {key}: {relpath} ({lc} lines) - {title}")
        sys.exit(1)

    key, relpath, title, total_lines = matches[0]
    filepath = os.path.join(MODULAR_DIR, relpath.replace("/", os.sep))

    # If it's a directory, list files in it
    if os.path.isdir(filepath):
        print(f"Module: {title}")
        print(f"Key: {key} | Path: {relpath} ({total_lines} lines total)")
        print("=" * 70)
        for root, _dirs, fnames in os.walk(filepath):
            for fn in sorted(fnames):
                if fn.endswith(".py"):
                    fp = os.path.join(root, fn)
                    rel = os.path.relpath(fp, MODULAR_DIR).replace(os.sep, "/")
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        lc = sum(1 for _ in f)
                    print(f"  {rel:<40s}  {lc:>5} lines")
        print()
        print("  Use bob_find.py <specific_key> to view a specific file.")
        sys.exit(0)

    # Show file content
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    file_lines = len(lines)
    show_lines = file_lines if args.full else min(args.lines, file_lines)

    print(f"Module: {title}")
    print(f"Key: {key} | Path: {relpath} ({file_lines} lines)")
    if not args.full and show_lines < file_lines:
        print(f"Showing first {show_lines} lines (use --full for all)")
    print("=" * 70)

    for i in range(show_lines):
        line_num = i + 1
        print(f"{line_num:>6}  {lines[i]}", end="")

    if not args.full and show_lines < file_lines:
        remaining = file_lines - show_lines
        print(f"\n  ... {remaining} more lines (use --full or --lines {file_lines})")


if __name__ == "__main__":
    main()
