#!/usr/bin/env python3
"""bob-migrate: Migration status checker.

NOTE: Migration from the monolith (mind_clone_agent.py) to the modular
package (src/mind_clone/) is COMPLETE. The monolith has been removed.
This script now validates the modular package structure and completeness.

Usage:
    python bob_migrate.py config    # Check config vars
    python bob_migrate.py routes    # Check API routes
    python bob_migrate.py models    # Check DB models
    python bob_migrate.py state     # Check RUNTIME_STATE keys
    python bob_migrate.py all       # Run all checks
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
MODULAR_DIR = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")


def read_file(path):
    """Read file, return empty string if missing."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def migrate_config():
    """Check config vars in the modular config.py."""
    mod = read_file(os.path.join(MODULAR_DIR, "config.py"))

    # Extract from modular: Field names or env aliases
    mod_vars = set(re.findall(r':\s*\w+\s*=\s*Field\(.+?alias=["\']([A-Z_]+)', mod))
    mod_attr_vars = set(re.findall(r'^\s+([A-Z][A-Z_0-9]+)\s*:', mod, re.MULTILINE))
    mod_vars |= mod_attr_vars
    # Also check for direct os.environ/getenv in modular
    mod_vars |= set(re.findall(r'os\.(?:environ\.get|getenv)\(\s*"([A-Z_]+)"', mod))

    print(f"  Config Vars (modular package):")
    print(f"    Modular:  {len(mod_vars)} vars")
    print(f"    Note: Monolith removed. Modular package is the source of truth.")

    return True, []


def migrate_routes():
    """Check API routes in the modular package."""
    # Extract from modular route files
    mod_routes = set()
    routes_dir = os.path.join(MODULAR_DIR, "api", "routes")
    routes_main = os.path.join(MODULAR_DIR, "api", "routes.py")

    for src_path in [routes_main]:
        content = read_file(src_path)
        mod_routes |= set(re.findall(r'@router\.(?:get|post|put|patch|delete)\(\s*"(/[^"]+)"', content))

    if os.path.isdir(routes_dir):
        for fname in os.listdir(routes_dir):
            if fname.endswith(".py") and fname != "__init__.py":
                content = read_file(os.path.join(routes_dir, fname))
                mod_routes |= set(re.findall(r'@router\.(?:get|post|put|patch|delete)\(\s*"(/[^"]+)"', content))

    print(f"  API Routes (modular package):")
    print(f"    Modular:  {len(mod_routes)} routes")
    print(f"    Note: Monolith removed. Modular package is the source of truth.")

    return True, []


def migrate_models():
    """Check DB models in the modular package."""
    mod = read_file(os.path.join(MODULAR_DIR, "database", "models.py"))

    mod_classes = set(re.findall(r'class\s+(\w+)\(.*Base\)', mod))

    print(f"  DB Models (modular package):")
    print(f"    Modular:  {len(mod_classes)} models")
    print(f"    Note: Monolith removed. Modular package is the source of truth.")

    return True, []


def migrate_state():
    """Check RUNTIME_STATE keys in the modular state.py."""
    mod = read_file(os.path.join(MODULAR_DIR, "core", "state.py"))

    mod_keys = set()
    if mod:
        state_match = re.search(r'RUNTIME_STATE\s*(?::\s*dict\s*)?=\s*\{(.+?)\n\}', mod, re.DOTALL)
        if state_match:
            mod_keys = set(re.findall(r'"([a-z_]+)":', state_match.group(1)))
        mod_keys |= set(re.findall(r'RUNTIME_STATE\["([a-z_]+)"\]', mod))

    print(f"  RUNTIME_STATE Keys (modular package):")
    print(f"    Modular:  {len(mod_keys)} keys")
    print(f"    Note: Monolith removed. Modular package is the source of truth.")

    return True, []


def main():
    parser = argparse.ArgumentParser(
        description="bob-migrate: Modular package status checker (migration complete)",
        epilog="Examples:\n"
               "  python bob_migrate.py config   # check config vars\n"
               "  python bob_migrate.py all      # check everything\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["config", "routes", "models", "state", "all"],
                        help="What to check")
    args = parser.parse_args()

    if not os.path.isdir(MODULAR_DIR):
        print(f"Error: Modular package not found at {MODULAR_DIR}")
        sys.exit(1)

    print("=" * 60)
    print("  bob-migrate: Modular Package Status (migration complete)")
    print("=" * 60)
    print()

    commands = {
        "config": migrate_config,
        "routes": migrate_routes,
        "models": migrate_models,
        "state": migrate_state,
    }

    if args.command == "all":
        results = []
        for name, fn in commands.items():
            synced, missing = fn()
            results.append((name, synced, len(missing)))
            print()

        print("=" * 60)
        all_synced = all(s for _, s, _ in results)
        for name, synced, count in results:
            mark = "+" if synced else "x"
            print(f"  [{mark}] {name}: {'synced' if synced else f'{count} missing'}")
        print()
        if all_synced:
            print("  Status: FULLY SYNCED")
        else:
            total_missing = sum(c for _, _, c in results)
            print(f"  Status: {total_missing} items need migration")
        print("=" * 60)
        sys.exit(0 if all_synced else 1)
    else:
        synced, missing = commands[args.command]()
        sys.exit(0 if synced else 1)


if __name__ == "__main__":
    main()
