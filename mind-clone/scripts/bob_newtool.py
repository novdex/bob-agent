#!/usr/bin/env python3
"""bob-newtool: Generate all 5 pieces for a new Bob tool.

Usage:
    python bob_newtool.py search_images "Search for images online" --params query:string,max_results:integer
    python bob_newtool.py analyze_text "Analyze text sentiment" --params text:string --safe
"""

import argparse
import json
import sys
import textwrap


def parse_params(params_str):
    """Parse 'name:type,name:type' into list of (name, type, required)."""
    if not params_str:
        return []
    params = []
    for p in params_str.split(","):
        p = p.strip()
        if ":" in p:
            name, ptype = p.split(":", 1)
            params.append((name.strip(), ptype.strip(), True))
        else:
            params.append((p.strip(), "string", True))
    return params


def generate_implementation(tool_name, description, params):
    """Generate the tool implementation function."""
    func_name = f"tool_{tool_name}"
    param_list = []
    for name, ptype, _ in params:
        py_type = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}.get(ptype, "str")
        param_list.append(f"{name}: {py_type}")

    params_str = ", ".join(param_list) if param_list else ""
    args_extract = []
    for name, ptype, _ in params:
        args_extract.append(f'    {name} = args.get("{name}")')

    return textwrap.dedent(f'''\
    # --- {tool_name} ---
    def {func_name}({params_str}) -> dict:
        """{description}"""
        try:
            # TODO: Implement {tool_name}
            result = "Not yet implemented"
            return {{"ok": True, "result": result}}
        except Exception as e:
            log.warning("{func_name} failed: %s", e)
            return {{"ok": False, "error": str(e)}}
    ''')


def generate_schema(tool_name, description, params):
    """Generate the OpenAI function calling schema."""
    properties = {}
    required = []
    for name, ptype, req in params:
        properties[name] = {
            "type": ptype,
            "description": f"The {name.replace('_', ' ')}",
        }
        if req:
            required.append(name)

    schema = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
    return json.dumps(schema, indent=4)


def generate_dispatch(tool_name, params):
    """Generate the TOOL_DISPATCH entry."""
    args_list = []
    for name, ptype, req in params:
        if req:
            args_list.append(f'args["{name}"]')
        else:
            default = {"string": '""', "integer": "0", "number": "0.0", "boolean": "False"}.get(ptype, "None")
            args_list.append(f'args.get("{name}", {default})')
    args_str = ", ".join(args_list)
    return f'    "{tool_name}": lambda args: tool_{tool_name}({args_str}),'


def generate_toolset_entry(tool_name, is_safe):
    """Generate the ALL_TOOL_NAMES and optional SAFE_TOOL_NAMES entries."""
    lines = [f'    "{tool_name}",  # <-- ADD to ALL_TOOL_NAMES']
    if is_safe:
        lines.append(f'    "{tool_name}",  # <-- ADD to SAFE_TOOL_NAMES')
    return "\n".join(lines)


def generate_modular_impl(tool_name, description, params):
    """Generate modular package implementation."""
    func_name = f"tool_{tool_name}"
    param_list = []
    for name, ptype, _ in params:
        py_type = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}.get(ptype, "str")
        param_list.append(f"{name}: {py_type}")
    params_str = ", ".join(param_list)

    return textwrap.dedent(f'''\
    # In src/mind_clone/tools/<category>.py:

    def {func_name}({params_str}) -> dict:
        """{description}"""
        try:
            result = "Not yet implemented"
            return {{"ok": True, "result": result}}
        except Exception as e:
            return {{"ok": False, "error": str(e)}}
    ''')


def main():
    parser = argparse.ArgumentParser(description="Generate scaffolding for a new Bob tool")
    parser.add_argument("tool_name", help="Tool name (snake_case, e.g., search_images)")
    parser.add_argument("description", help="Tool description")
    parser.add_argument("--params", "-p", default="", help="Parameters as name:type,name:type")
    parser.add_argument("--safe", action="store_true", help="Mark as safe/read-only tool")
    args = parser.parse_args()

    params = parse_params(args.params)
    name = args.tool_name
    desc = args.description

    print("=" * 70)
    print(f"  bob-newtool: Scaffolding for '{name}'")
    print("=" * 70)

    # 1. Implementation
    print("\n[1/4] TOOL IMPLEMENTATION")
    print("     Add to appropriate file in src/mind_clone/tools/")
    print("-" * 70)
    print(generate_modular_impl(name, desc, params))

    # 2. Schema
    print("\n[2/4] TOOL SCHEMA (OpenAI Function Calling Format)")
    print("     Paste into src/mind_clone/tools/schemas.py TOOL_DEFINITIONS list")
    print("-" * 70)
    print(generate_schema(name, desc, params))
    print(",")

    # 3. Dispatch
    print("\n[3/4] TOOL DISPATCH ENTRY")
    print("     Paste into src/mind_clone/tools/registry.py TOOL_DISPATCH dict")
    print("-" * 70)
    print(generate_dispatch(name, params))

    # 4. Tool sets
    print("\n[4/4] TOOL SET UPDATES")
    print("     Add to ALL_TOOL_NAMES in src/mind_clone/core/security.py", end="")
    if args.safe:
        print(" and SAFE_TOOL_NAMES")
    else:
        print()
    print("-" * 70)
    print(generate_toolset_entry(name, args.safe))

    # Reminder
    print("=" * 70)
    print("  Checklist:")
    print(f"  [ ] Implementation in src/mind_clone/tools/<category>.py")
    print(f"  [ ] Schema in src/mind_clone/tools/schemas.py")
    print(f"  [ ] Dispatch in src/mind_clone/tools/registry.py")
    print(f"  [ ] Added to ALL_TOOL_NAMES" + (" + SAFE_TOOL_NAMES" if args.safe else "") + " in src/mind_clone/core/security.py")
    print(f"  [ ] New env vars in .env.example (if any)")
    print(f"  [ ] Run bob-check to validate")
    print("=" * 70)


if __name__ == "__main__":
    main()
