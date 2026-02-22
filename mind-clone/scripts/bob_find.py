#!/usr/bin/env python3
"""bob-find: Navigate the monolith by section name.

Usage:
    python bob_find.py                  # List all sections
    python bob_find.py registry         # Show first 50 lines of registry section
    python bob_find.py reg              # Fuzzy match: "reg" -> "registry"
    python bob_find.py llm --lines 100  # Show first 100 lines
    python bob_find.py tools --full     # Show entire section
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
MONOLITH = os.path.join(MIND_CLONE_DIR, "mind_clone_agent.py")

DEFAULT_LINES = 50


def parse_sections(filepath):
    """Parse section markers from the monolith and return ordered list of (name, start, end)."""
    sections = []
    current_name = None
    current_start = None

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Match "# ===" section headers
        if stripped.startswith("# ==") and len(stripped) > 10:
            # Look at the next non-empty, non-separator line for the section title
            title = None
            for j in range(i, min(i + 5, total_lines)):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("# =="):
                    # Extract title from comment
                    if next_line.startswith("#"):
                        title = next_line.lstrip("# ").strip()
                    break

            if title:
                # Close previous section
                if current_name is not None:
                    sections.append((current_name, current_start, i - 1))
                current_name = title
                current_start = i

    # Close last section
    if current_name is not None:
        sections.append((current_name, current_start, total_lines))

    return sections, total_lines


def make_short_key(title):
    """Create a short lookup key from a section title."""
    title_lower = title.lower()
    # Map known section titles to short keys
    key_map = {
        "config": ["configuration", "config", "env var"],
        "glove": ["glove", "vector memory", "embedding"],
        "models": ["section 1:", "database model"],
        "helpers": ["section 1b:", "session integrity", "ssrf", "queue mode"],
        "tools": ["section 2:", "tool implementation"],
        "browser": ["pillar 5:", "browser tool"],
        "registry": ["section 3:", "tool registry"],
        "identity": ["section 4:", "identity loader"],
        "pillar1": ["pillar 1:", "in-loop reflection"],
        "pillar4": ["pillar 4:", "task lesson"],
        "authority": ["section 5:", "autonomy directive"],
        "memory": ["section 6:", "conversation memory"],
        "llm": ["section 7:", "llm client"],
        "loop": ["section 8:", "agent loop", "the brain"],
        "tasks": ["section 8b:", "autonomous task", "task engine"],
        "users": ["section 9:", "user", "identity management"],
        "telegram": ["section 10:", "telegram"],
        "fastapi": ["section 11:", "fastapi application"],
        "entry": ["entry point", "__main__"],
    }
    for key, patterns in key_map.items():
        if any(p in title_lower for p in patterns):
            return key
    # Fallback: first word
    words = re.findall(r"[a-z]+", title_lower)
    return words[0] if words else "unknown"


def fuzzy_match(query, sections_with_keys):
    """Find sections matching a fuzzy query."""
    query_lower = query.lower()
    matches = []
    for key, title, start, end in sections_with_keys:
        if query_lower == key:
            matches.append((key, title, start, end))
        elif query_lower in key or query_lower in title.lower():
            matches.append((key, title, start, end))
    return matches


def main():
    parser = argparse.ArgumentParser(description="Navigate the Bob monolith by section")
    parser.add_argument("section", nargs="?", help="Section name or fuzzy query")
    parser.add_argument("--lines", "-n", type=int, default=DEFAULT_LINES, help="Lines to show (default 50)")
    parser.add_argument("--full", "-f", action="store_true", help="Show entire section")
    args = parser.parse_args()

    if not os.path.exists(MONOLITH):
        print(f"Error: Monolith not found at {MONOLITH}")
        sys.exit(1)

    sections, total_lines = parse_sections(MONOLITH)
    sections_with_keys = [
        (make_short_key(title), title, start, end)
        for title, start, end in sections
    ]

    # List mode
    if not args.section:
        print(f"Bob Monolith: {total_lines:,} lines, {len(sections)} sections")
        print("=" * 70)
        print(f"  {'Key':<12} {'Lines':>12}  {'Size':>6}  Title")
        print("-" * 70)
        for key, title, start, end in sections_with_keys:
            size = end - start + 1
            print(f"  {key:<12} {start:>5}-{end:<5}  {size:>5}  {title}")
        print()
        print("Usage: python bob_find.py <key>  (e.g., 'registry', 'llm', 'tools')")
        sys.exit(0)

    # Find mode
    matches = fuzzy_match(args.section, sections_with_keys)
    if not matches:
        print(f"No section matching '{args.section}'")
        print("Available keys:", ", ".join(k for k, _, _, _ in sections_with_keys))
        sys.exit(1)

    if len(matches) > 1 and not any(m[0] == args.section.lower() for m in matches):
        print(f"Multiple matches for '{args.section}':")
        for key, title, start, end in matches:
            print(f"  {key}: {title} (lines {start}-{end})")
        sys.exit(1)

    key, title, start, end = matches[0]
    section_size = end - start + 1
    show_lines = section_size if args.full else min(args.lines, section_size)

    print(f"Section: {title}")
    print(f"Key: {key} | Lines {start}-{end} ({section_size} lines)")
    if not args.full and show_lines < section_size:
        print(f"Showing first {show_lines} lines (use --full for all)")
    print("=" * 70)

    with open(MONOLITH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for i in range(start - 1, min(start - 1 + show_lines, end)):
        line_num = i + 1
        print(f"{line_num:>6}  {lines[i]}", end="")

    if not args.full and show_lines < section_size:
        remaining = section_size - show_lines
        print(f"\n  ... {remaining} more lines (use --full or --lines {section_size})")


if __name__ == "__main__":
    main()
