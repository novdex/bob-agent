#!/usr/bin/env python3
"""bob-sync: Compare monolith vs modular package and report drift.

Checks 6 sync points:
  1. Tool count (ALL_TOOL_NAMES vs modular schemas)
  2. Tool names (TOOL_DISPATCH keys vs modular registry)
  3. DB models (class definitions)
  4. Config env vars
  5. API routes (decorators)
  6. File existence (expected modular files)
"""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(MIND_CLONE_DIR)
MONOLITH = os.path.join(MIND_CLONE_DIR, "mind_clone_agent.py")
MODULAR_DIR = os.path.join(MIND_CLONE_DIR, "src", "mind_clone")


def read_file(path):
    """Read file content, return empty string if missing."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def count_pattern(text, pattern):
    """Count regex matches in text."""
    return len(re.findall(pattern, text))


def extract_quoted_strings(text, pattern):
    """Extract quoted strings following a pattern match region."""
    matches = re.findall(r'"([a-z_]+)"', text)
    return set(matches)


def check_tools():
    """Compare tool counts between monolith and modular."""
    mono = read_file(MONOLITH)
    mod_schemas = read_file(os.path.join(MODULAR_DIR, "tools", "schemas.py"))
    mod_registry = read_file(os.path.join(MODULAR_DIR, "tools", "registry.py"))

    # Monolith: count ALL_TOOL_NAMES entries
    all_tools_match = re.search(r'ALL_TOOL_NAMES\s*=\s*\{([^}]+)\}', mono, re.DOTALL)
    mono_tools = set()
    if all_tools_match:
        mono_tools = set(re.findall(r'"([a-z_]+)"', all_tools_match.group(1)))

    # Monolith: TOOL_DISPATCH keys
    dispatch_match = re.search(r'TOOL_DISPATCH\s*=\s*\{(.+?)^\}', mono, re.DOTALL | re.MULTILINE)
    mono_dispatch = set()
    if dispatch_match:
        mono_dispatch = set(re.findall(r'"([a-z_]+)":', dispatch_match.group(1)))

    # Modular: count tool function schemas
    mod_schema_tools = set(re.findall(r'"name":\s*"([a-z_]+)"', mod_schemas))

    # Modular: registry dispatch keys
    mod_dispatch_tools = set(re.findall(r'"([a-z_]+)":', mod_registry))

    return {
        "mono_all_tools": len(mono_tools),
        "mono_dispatch": len(mono_dispatch),
        "mod_schemas": len(mod_schema_tools),
        "mod_dispatch": len(mod_dispatch_tools),
        "mono_only_tools": mono_tools - mod_schema_tools if mod_schema_tools else set(),
        "mod_only_tools": mod_schema_tools - mono_tools if mono_tools else set(),
    }


def check_models():
    """Compare DB model counts."""
    mono = read_file(MONOLITH)
    mod_models = read_file(os.path.join(MODULAR_DIR, "database", "models.py"))

    mono_classes = set(re.findall(r'class\s+(\w+)\(.*Base\)', mono))
    mod_classes = set(re.findall(r'class\s+(\w+)\(.*Base\)', mod_models))

    return {
        "mono_count": len(mono_classes),
        "mod_count": len(mod_classes),
        "mono_only": mono_classes - mod_classes,
        "mod_only": mod_classes - mono_classes,
    }


def check_config():
    """Compare config env var counts."""
    mono = read_file(MONOLITH)
    mod_config = read_file(os.path.join(MODULAR_DIR, "config.py"))

    # Monolith: os.environ.get / os.getenv calls
    mono_vars = set(re.findall(r'os\.(?:environ\.get|getenv)\(\s*["\']([A-Z_]+)', mono))

    # Modular: Pydantic field definitions with env aliases or Field names
    mod_vars = set(re.findall(r':\s*\w+\s*=\s*Field\(.+?alias=["\']([A-Z_]+)', mod_config))
    # Also match uppercase attribute names that map to env vars
    mod_attr_vars = set(re.findall(r'^\s+([A-Z][A-Z_0-9]+)\s*:', mod_config, re.MULTILINE))
    mod_vars = mod_vars | mod_attr_vars

    return {
        "mono_count": len(mono_vars),
        "mod_count": len(mod_vars),
    }


def check_routes():
    """Compare API route counts."""
    mono = read_file(MONOLITH)
    mod_routes_dir = os.path.join(MODULAR_DIR, "api", "routes")
    mod_routes_main = read_file(os.path.join(MODULAR_DIR, "api", "routes.py"))

    # Monolith: @app.get/post/put/delete decorators
    mono_routes = count_pattern(mono, r'@app\.(get|post|put|patch|delete)\(')

    # Modular: @router.get/post + any route files
    mod_count = count_pattern(mod_routes_main, r'@router\.(get|post|put|patch|delete)\(')
    if os.path.isdir(mod_routes_dir):
        for fname in os.listdir(mod_routes_dir):
            if fname.endswith(".py") and fname != "__init__.py":
                content = read_file(os.path.join(mod_routes_dir, fname))
                mod_count += count_pattern(content, r'@router\.(get|post|put|patch|delete)\(')

    return {"mono_count": mono_routes, "mod_count": mod_count}


def check_files():
    """Verify expected modular package files exist."""
    expected = [
        "config.py",
        "__main__.py",
        "__init__.py",
        "agent/__init__.py",
        "agent/identity.py",
        "agent/llm.py",
        "agent/loop.py",
        "agent/memory.py",
        "agent/reflection.py",
        "api/__init__.py",
        "api/app.py",
        "api/factory.py",
        "api/models.py",
        "api/routes.py",
        "api/routes/chat.py",
        "api/routes/runtime.py",
        "api/routes/tasks.py",
        "api/routes/tools.py",
        "core/__init__.py",
        "core/state.py",
        "core/security.py",
        "database/__init__.py",
        "database/models.py",
        "tools/__init__.py",
        "tools/registry.py",
        "tools/schemas.py",
        "tools/files.py",
        "tools/web.py",
        "tools/code.py",
        "tools/email.py",
        "tools/desktop.py",
        "tools/vector_memory.py",
        "services/__init__.py",
        "services/task_engine.py",
        "services/scheduler.py",
        "services/telegram.py",
    ]
    present = []
    missing = []
    for f in expected:
        path = os.path.join(MODULAR_DIR, f.replace("/", os.sep))
        if os.path.exists(path):
            present.append(f)
        else:
            missing.append(f)
    return {"present": present, "missing": missing, "total": len(expected)}


def print_check(name, passed, detail=""):
    mark = "+" if passed else "x"
    status = "OK" if passed else "DRIFT"
    line = f"  [{mark}] {name}: {status}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return passed


def main():
    print("=" * 60)
    print("  bob-sync: Monolith vs Modular Sync Report")
    print("=" * 60)
    print()

    if not os.path.exists(MONOLITH):
        print(f"Error: Monolith not found at {MONOLITH}")
        sys.exit(1)
    if not os.path.isdir(MODULAR_DIR):
        print(f"Error: Modular package not found at {MODULAR_DIR}")
        sys.exit(1)

    results = []

    # 1. Tool schemas
    tools = check_tools()
    tool_ok = tools["mod_schemas"] > 0
    detail = f"monolith={tools['mono_all_tools']}, modular={tools['mod_schemas']}"
    if tools["mono_only_tools"]:
        mono_sample = list(tools["mono_only_tools"])[:5]
        detail += f", mono-only: {mono_sample}"
    results.append(print_check("Tool Schemas", tool_ok, detail))

    # 2. Tool dispatch
    disp_ok = tools["mod_dispatch"] > 0
    detail = f"monolith={tools['mono_dispatch']}, modular={tools['mod_dispatch']}"
    results.append(print_check("Tool Dispatch", disp_ok, detail))

    # 3. DB models
    models = check_models()
    model_ok = models["mod_count"] > 0
    detail = f"monolith={models['mono_count']}, modular={models['mod_count']}"
    if models["mono_only"]:
        mono_sample = list(models["mono_only"])[:5]
        detail += f", mono-only: {mono_sample}"
    results.append(print_check("DB Models", model_ok, detail))

    # 4. Config vars
    config = check_config()
    config_ok = config["mod_count"] > 0
    detail = f"monolith={config['mono_count']}, modular={config['mod_count']}"
    results.append(print_check("Config Vars", config_ok, detail))

    # 5. API routes
    routes = check_routes()
    routes_ok = routes["mod_count"] > 0
    detail = f"monolith={routes['mono_count']}, modular={routes['mod_count']}"
    results.append(print_check("API Routes", routes_ok, detail))

    # 6. File existence
    files = check_files()
    files_ok = len(files["missing"]) == 0
    detail = f"{len(files['present'])}/{files['total']} present"
    if files["missing"]:
        detail += f", missing: {files['missing'][:5]}"
    results.append(print_check("Package Files", files_ok, detail))

    # Summary
    passed = sum(results)
    total = len(results)
    print()
    print("-" * 60)
    print(f"  Sync Score: {passed}/{total}")
    if passed == total:
        print("  Status: FULLY SYNCED")
    else:
        print("  Status: DRIFT DETECTED — review items marked [x]")
    print("-" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
