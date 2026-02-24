#!/usr/bin/env python3
"""bob-log: Generate a CHANGELOG.md entry from git diff or manual input.

Usage:
    python bob_log.py --auto                          # From git diff
    python bob_log.py --title "Added X" --summary "Details here"  # Manual
    python bob_log.py --auto --write                  # Auto + prepend to CHANGELOG.md
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(MIND_CLONE_DIR)
CHANGELOG = os.path.join(MIND_CLONE_DIR, "CHANGELOG.md")


def git_diff_stat():
    """Get git diff --stat output."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=ROOT_DIR,
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def git_diff_names():
    """Get list of changed file names."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=ROOT_DIR,
            capture_output=True, text=True, timeout=10,
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        return []


def git_staged_names():
    """Get list of staged file names."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=ROOT_DIR,
            capture_output=True, text=True, timeout=10,
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        return []


def git_untracked():
    """Get list of untracked files."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT_DIR,
            capture_output=True, text=True, timeout=10,
        )
        return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        return []


def categorize_files(files):
    """Group files by area."""
    areas = {
        "modular": [],
        "frontend": [],
        "tests": [],
        "scripts": [],
        "config": [],
        "docs": [],
        "other": [],
    }
    for f in files:
        if f.startswith("src/mind_clone/") or f.startswith("src\\mind_clone\\"):
            areas["modular"].append(f)
        elif "mind-clone-ui" in f:
            areas["frontend"].append(f)
        elif f.startswith("tests/") or f.startswith("tests\\"):
            areas["tests"].append(f)
        elif "scripts/" in f or "scripts\\" in f:
            areas["scripts"].append(f)
        elif f.endswith((".toml", ".yml", ".yaml", ".json", ".cfg", "Dockerfile")):
            areas["config"].append(f)
        elif f.endswith(".md"):
            areas["docs"].append(f)
        else:
            areas["other"].append(f)
    return {k: v for k, v in areas.items() if v}


def generate_auto_summary(files):
    """Generate a summary from changed file names."""
    areas = categorize_files(files)
    parts = []
    for area, area_files in areas.items():
        names = [os.path.basename(f) for f in area_files[:5]]
        suffix = f" (+{len(area_files) - 5} more)" if len(area_files) > 5 else ""
        parts.append(f"  - **{area}**: {', '.join(names)}{suffix}")
    return "\n".join(parts)


def generate_changes_list(files):
    """Generate numbered changes list from files."""
    areas = categorize_files(files)
    items = []
    idx = 1
    for area, area_files in areas.items():
        for f in area_files:
            items.append(f"{idx}. Modified `{f}`")
            idx += 1
    return "\n".join(items) if items else "1. (No file changes detected)"


def format_entry(title, summary, changes, validation=""):
    """Format a CHANGELOG.md entry."""
    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"""## {today} | Worker: Claude Code | {title}

### Session Summary
{summary}

### Changes Made
{changes}

### Validation Outcomes
{validation if validation else "- `python mind-clone/scripts/bob_check.py` — (pending)"}

---
"""
    return entry


def main():
    parser = argparse.ArgumentParser(description="Generate CHANGELOG.md entry")
    parser.add_argument("--auto", action="store_true", help="Auto-generate from git diff")
    parser.add_argument("--title", "-t", default="", help="Entry title")
    parser.add_argument("--summary", "-s", default="", help="Session summary")
    parser.add_argument("--validation", "-v", default="", help="Validation outcomes")
    parser.add_argument("--write", "-w", action="store_true", help="Prepend to CHANGELOG.md")
    args = parser.parse_args()

    if not args.auto and not args.title:
        parser.print_help()
        print("\nError: Provide --auto or --title")
        sys.exit(1)

    if args.auto:
        # Gather all changed files
        changed = git_diff_names()
        staged = git_staged_names()
        untracked = git_untracked()
        all_files = list(set(changed + staged + untracked))

        if not all_files:
            print("No changes detected (git diff is clean)")
            sys.exit(0)

        title = args.title or "Development Session"
        summary = args.summary or f"Modified {len(all_files)} file(s):\n{generate_auto_summary(all_files)}"
        changes = generate_changes_list(all_files)
    else:
        title = args.title
        summary = args.summary or "(Summary not provided)"
        changes = "(Changes not auto-detected — manual entry)"

    entry = format_entry(title, summary, changes, args.validation)

    print("=" * 60)
    print("  bob-log: Generated CHANGELOG Entry")
    print("=" * 60)
    print()
    print(entry)

    if args.write:
        if os.path.exists(CHANGELOG):
            with open(CHANGELOG, "r", encoding="utf-8") as f:
                existing = f.read()
            with open(CHANGELOG, "w", encoding="utf-8") as f:
                f.write(entry + "\n" + existing)
            print(f"  Entry prepended to {CHANGELOG}")
        else:
            with open(CHANGELOG, "w", encoding="utf-8") as f:
                f.write("# CHANGELOG\n\n" + entry)
            print(f"  Created {CHANGELOG}")
    else:
        print("  (Use --write to prepend to CHANGELOG.md)")


if __name__ == "__main__":
    main()
