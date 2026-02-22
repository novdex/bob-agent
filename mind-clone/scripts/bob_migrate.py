#!/usr/bin/env python3
"""bob-migrate: Sync new features from monolith to modular package.

Detects additions in the monolith that haven't been mirrored to
src/mind_clone/ and generates the needed code or shows a diff.

Usage:
    python bob_migrate.py config    # Sync config vars
    python bob_migrate.py routes    # Sync API routes
    python bob_migrate.py models    # Sync DB models
    python bob_migrate.py state     # Sync RUNTIME_STATE keys
    python bob_migrate.py all       # Run all checks
"""

import argparse
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
MONOLITH = os.path.join(MIND_CLONE_DIR, "mind_clone_agent.py")
MODULAR_DIR = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")


def read_file(path):
    """Read file, return empty string if missing."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def migrate_config():
    """Find config vars in monolith not present in modular config.py."""
    mono = read_file(MONOLITH)
    mod = read_file(os.path.join(MODULAR_DIR, "config.py"))

    # Extract env var names from monolith: _env_flag("NAME", ...) and _env_int("NAME", ...)
    # and os.environ.get("NAME") and os.getenv("NAME")
    mono_vars = set(re.findall(r'_env_(?:flag|int)\(\s*"([A-Z_]+)"', mono))
    mono_vars |= set(re.findall(r'os\.(?:environ\.get|getenv)\(\s*"([A-Z_]+)"', mono))

    # Extract from modular: Field names or env aliases
    mod_vars = set(re.findall(r':\s*\w+\s*=\s*Field\(.+?alias=["\']([A-Z_]+)', mod))
    mod_attr_vars = set(re.findall(r'^\s+([A-Z][A-Z_0-9]+)\s*:', mod, re.MULTILINE))
    mod_vars |= mod_attr_vars
    # Also check for direct os.environ/getenv in modular
    mod_vars |= set(re.findall(r'os\.(?:environ\.get|getenv)\(\s*"([A-Z_]+)"', mod))

    missing = sorted(mono_vars - mod_vars)
    present = mono_vars & mod_vars

    print(f"  Config Vars:")
    print(f"    Monolith: {len(mono_vars)} vars")
    print(f"    Modular:  {len(mod_vars)} vars")
    print(f"    Synced:   {len(present)} vars")
    print(f"    Missing:  {len(missing)} vars")

    if missing:
        print(f"\n  Missing in modular config.py:")
        for var in missing[:30]:
            print(f"    + {var}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")

    return len(missing) == 0, missing


def migrate_routes():
    """Find API routes in monolith not in modular routes."""
    mono = read_file(MONOLITH)

    # Extract route paths from monolith: @app.get("/path") etc
    mono_routes = set(re.findall(r'@app\.(?:get|post|put|patch|delete)\(\s*"(/[^"]+)"', mono))

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

    missing = sorted(mono_routes - mod_routes)
    present = mono_routes & mod_routes

    print(f"  API Routes:")
    print(f"    Monolith: {len(mono_routes)} routes")
    print(f"    Modular:  {len(mod_routes)} routes")
    print(f"    Synced:   {len(present)} routes")
    print(f"    Missing:  {len(missing)} routes")

    if missing:
        print(f"\n  Missing in modular routes:")
        for route in missing[:30]:
            print(f"    + {route}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")

    return len(missing) == 0, missing


def migrate_models():
    """Find DB models in monolith not in modular models."""
    mono = read_file(MONOLITH)
    mod = read_file(os.path.join(MODULAR_DIR, "database", "models.py"))

    mono_classes = set(re.findall(r'class\s+(\w+)\(.*Base\)', mono))
    mod_classes = set(re.findall(r'class\s+(\w+)\(.*Base\)', mod))

    missing = sorted(mono_classes - mod_classes)
    present = mono_classes & mod_classes

    print(f"  DB Models:")
    print(f"    Monolith: {len(mono_classes)} models")
    print(f"    Modular:  {len(mod_classes)} models")
    print(f"    Synced:   {len(present)} models")
    print(f"    Missing:  {len(missing)} models")

    if missing:
        print(f"\n  Missing in modular models.py:")
        for model in missing[:20]:
            print(f"    + {model}")

    return len(missing) == 0, missing


def migrate_state():
    """Find RUNTIME_STATE keys in monolith not in modular state.py."""
    mono = read_file(MONOLITH)
    mod = read_file(os.path.join(MODULAR_DIR, "core", "state.py"))

    # Extract keys from RUNTIME_STATE dict initialization
    state_match = re.search(r'RUNTIME_STATE\s*(?::\s*dict\s*)?=\s*\{(.+?)\n\}', mono, re.DOTALL)
    mono_keys = set()
    if state_match:
        mono_keys = set(re.findall(r'"([a-z_]+)":', state_match.group(1)))

    # Also find dynamic RUNTIME_STATE assignments
    dynamic_keys = set(re.findall(r'RUNTIME_STATE\["([a-z_]+)"\]', mono))
    mono_keys |= dynamic_keys

    mod_keys = set()
    if mod:
        state_match = re.search(r'RUNTIME_STATE\s*(?::\s*dict\s*)?=\s*\{(.+?)\n\}', mod, re.DOTALL)
        if state_match:
            mod_keys = set(re.findall(r'"([a-z_]+)":', state_match.group(1)))
        mod_keys |= set(re.findall(r'RUNTIME_STATE\["([a-z_]+)"\]', mod))

    missing = sorted(mono_keys - mod_keys)
    present = mono_keys & mod_keys

    print(f"  RUNTIME_STATE Keys:")
    print(f"    Monolith: {len(mono_keys)} keys")
    print(f"    Modular:  {len(mod_keys)} keys")
    print(f"    Synced:   {len(present)} keys")
    print(f"    Missing:  {len(missing)} keys")

    if missing:
        print(f"\n  Missing in modular state.py:")
        for key in missing[:40]:
            print(f"    + \"{key}\"")
        if len(missing) > 40:
            print(f"    ... and {len(missing) - 40} more")

    return len(missing) == 0, missing


def main():
    parser = argparse.ArgumentParser(
        description="bob-migrate: Sync monolith features to modular package",
        epilog="Examples:\n"
               "  python bob_migrate.py config   # check config vars\n"
               "  python bob_migrate.py all      # check everything\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=["config", "routes", "models", "state", "all"],
                        help="What to migrate")
    args = parser.parse_args()

    if not os.path.exists(MONOLITH):
        print(f"Error: Monolith not found at {MONOLITH}")
        sys.exit(1)
    if not os.path.isdir(MODULAR_DIR):
        print(f"Error: Modular package not found at {MODULAR_DIR}")
        sys.exit(1)

    print("=" * 60)
    print("  bob-migrate: Feature Migration Report")
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
