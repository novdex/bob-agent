#!/usr/bin/env python3
"""
Targeted mutation tester for the hardened oracle.

Applies controlled mutations to source code, runs the relevant test file,
and checks whether the oracle catches the mutation. A mutation that passes
all tests is a "survivor" — meaning the oracle has a blind spot.

Usage:
    python scripts/mutation_test.py [--module MODULE]
"""
import ast
import subprocess
import sys
import os
import textwrap
import tempfile
import shutil
from pathlib import Path

# Map: source module -> test file
MODULES = {
    "core/circuit.py": "tests/unit/test_circuit.py",
    "core/state.py": "tests/unit/test_state.py",
    "core/queue.py": "tests/unit/test_queue.py",
    "core/sandbox.py": "tests/unit/test_sandbox.py",
    "core/budget.py": "tests/unit/test_budget.py",
    "core/closed_loop.py": "tests/unit/test_closed_loop.py",
    "core/self_tune.py": "tests/unit/test_self_tune.py",
    "core/context_engine.py": "tests/unit/test_context_engine.py",
    "core/evaluation.py": "tests/unit/test_evaluation.py",
    "core/security.py": "tests/unit/test_security.py",
    "core/secrets.py": "tests/unit/test_secrets.py",
    "core/policies.py": "tests/unit/test_policies.py",
    "core/approvals.py": "tests/unit/test_approvals.py",
    "core/authorization.py": "tests/unit/test_authorization.py",
    "tools/registry.py": "tests/unit/test_registry.py",
    "tools/schemas.py": "tests/unit/test_schemas.py",
    "tools/basic.py": "tests/unit/test_tools.py",
    "tools/custom.py": "tests/unit/test_tools.py",
}

SRC_ROOT = Path(__file__).parent.parent / "src" / "mind_clone"
PROJECT_ROOT = Path(__file__).parent.parent


class Mutator:
    """Generates simple mutations on Python source code."""

    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines(keepends=True)

    def generate_mutations(self):
        """Yield (description, mutated_source) tuples."""
        mutations = []

        # Mutation 1: Negate boolean returns
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith("return True"):
                mutations.append((
                    f"L{i+1}: return True -> return False",
                    self._replace_line(i, line.replace("return True", "return False"))
                ))
            elif stripped.startswith("return False"):
                mutations.append((
                    f"L{i+1}: return False -> return True",
                    self._replace_line(i, line.replace("return False", "return True"))
                ))

        # Mutation 2: Flip comparisons
        for i, line in enumerate(self.lines):
            if " >= " in line and "def " not in line and "#" not in line.split(">=")[0]:
                mutations.append((
                    f"L{i+1}: >= -> <",
                    self._replace_line(i, line.replace(" >= ", " < ", 1))
                ))
            elif " <= " in line and "def " not in line and "#" not in line.split("<=")[0]:
                mutations.append((
                    f"L{i+1}: <= -> >",
                    self._replace_line(i, line.replace(" <= ", " > ", 1))
                ))
            elif " == " in line and "def " not in line and "#" not in line.split("==")[0]:
                mutations.append((
                    f"L{i+1}: == -> !=",
                    self._replace_line(i, line.replace(" == ", " != ", 1))
                ))
            elif " != " in line and "def " not in line and "#" not in line.split("!=")[0]:
                mutations.append((
                    f"L{i+1}: != -> ==",
                    self._replace_line(i, line.replace(" != ", " == ", 1))
                ))
            elif " > " in line and "def " not in line and " -> " not in line and "#" not in line.split(">")[0] and ">=" not in line:
                mutations.append((
                    f"L{i+1}: > -> <=",
                    self._replace_line(i, line.replace(" > ", " <= ", 1))
                ))
            elif " < " in line and "def " not in line and " <- " not in line and "#" not in line.split("<")[0] and "<=" not in line and "<<" not in line:
                mutations.append((
                    f"L{i+1}: < -> >=",
                    self._replace_line(i, line.replace(" < ", " >= ", 1))
                ))

        # Mutation 3: Change arithmetic
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if "def " in line or stripped.startswith("#") or stripped.startswith("import"):
                continue
            if " + " in line and "+=" not in line:
                mutations.append((
                    f"L{i+1}: + -> -",
                    self._replace_line(i, line.replace(" + ", " - ", 1))
                ))
            if " * " in line and "**" not in line and "import" not in line:
                mutations.append((
                    f"L{i+1}: * -> /",
                    self._replace_line(i, line.replace(" * ", " / ", 1))
                ))

        # Mutation 4: Remove return value (return None instead)
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith("return ") and stripped != "return None" and stripped != "return" and "return True" not in stripped and "return False" not in stripped:
                indent = line[:len(line) - len(line.lstrip())]
                mutations.append((
                    f"L{i+1}: return X -> return None",
                    self._replace_line(i, f"{indent}return None\n")
                ))

        # Mutation 5: Change 0 to 1 and 1 to 0 in assignments
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if "def " in line or stripped.startswith("#"):
                continue
            if "= 0" in line and "== 0" not in line and "!= 0" not in line and ">= 0" not in line and "<= 0" not in line and ".0" not in line:
                mutations.append((
                    f"L{i+1}: = 0 -> = 1",
                    self._replace_line(i, line.replace("= 0", "= 1", 1))
                ))

        return mutations

    def _replace_line(self, idx, new_line):
        lines = list(self.lines)
        lines[idx] = new_line
        return "".join(lines)


def run_test(test_file: str, src_file: str, mutated_source: str, timeout: int = 30):
    """Run a test with mutated source. Returns True if mutation was KILLED (test failed)."""
    original = src_file.read_text()
    try:
        src_file.write_text(mutated_source)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file), "-x", "-q", "--tb=no", "--no-header"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        return result.returncode != 0  # nonzero = test failed = mutation killed
    except subprocess.TimeoutExpired:
        return True  # timeout counts as killed
    finally:
        src_file.write_text(original)


def test_module(module_rel: str, test_rel: str):
    """Run all mutations on one module. Returns (killed, survived, errors, survivors_list)."""
    src_file = SRC_ROOT / module_rel
    test_file = PROJECT_ROOT / test_rel

    if not src_file.exists():
        print(f"  SKIP: {src_file} not found")
        return 0, 0, 0, []
    if not test_file.exists():
        print(f"  SKIP: {test_file} not found")
        return 0, 0, 0, []

    source = src_file.read_text()
    mutator = Mutator(source)
    mutations = mutator.generate_mutations()

    if not mutations:
        print(f"  No mutations generated for {module_rel}")
        return 0, 0, 0, []

    killed = 0
    survived = 0
    errors = 0
    survivors = []

    for desc, mutated in mutations:
        try:
            was_killed = run_test(test_file, src_file, mutated)
            if was_killed:
                killed += 1
            else:
                survived += 1
                survivors.append(desc)
        except Exception as e:
            errors += 1

    return killed, survived, errors, survivors


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mutation tester for Bob oracle")
    parser.add_argument("--module", help="Test only this module (e.g. core/circuit.py)")
    parser.add_argument("--modules", help="Comma-separated short names (e.g. circuit,security,budget)")
    parser.add_argument("--threshold", type=int, default=70, help="Minimum kill rate %% to pass (default: 70)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout per mutation in seconds (default: 30)")
    args = parser.parse_args()

    # Short name -> full path mapping
    SHORT_NAMES = {}
    for key in MODULES:
        short = key.split("/")[-1].replace(".py", "")
        SHORT_NAMES[short] = key

    if args.module:
        modules = {args.module: MODULES[args.module]}
    elif args.modules:
        modules = {}
        for name in args.modules.split(","):
            name = name.strip()
            if name in SHORT_NAMES:
                key = SHORT_NAMES[name]
                modules[key] = MODULES[key]
            elif name in MODULES:
                modules[name] = MODULES[name]
            else:
                print(f"WARNING: Unknown module '{name}', skipping")
        if not modules:
            print("ERROR: No valid modules specified")
            sys.exit(1)
    else:
        modules = MODULES

    print("=" * 70)
    print("MUTATION TESTING — Bob AGI Platform Oracle")
    print("=" * 70)

    total_killed = 0
    total_survived = 0
    total_errors = 0
    all_survivors = {}
    results = []

    for module_rel, test_rel in modules.items():
        print(f"\n--- {module_rel} ---")
        k, s, e, survivors = test_module(module_rel, test_rel)
        total_killed += k
        total_survived += s
        total_errors += e
        total = k + s
        rate = (k / total * 100) if total > 0 else 0
        results.append((module_rel, k, s, e, rate))
        print(f"  Mutations: {total} | Killed: {k} | Survived: {s} | Kill rate: {rate:.0f}%")
        if survivors:
            all_survivors[module_rel] = survivors
            for sv in survivors[:3]:
                print(f"    SURVIVOR: {sv}")
            if len(survivors) > 3:
                print(f"    ... and {len(survivors) - 3} more")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    total = total_killed + total_survived
    overall_rate = (total_killed / total * 100) if total > 0 else 0
    print(f"Total mutations: {total}")
    print(f"Killed: {total_killed}")
    print(f"Survived: {total_survived}")
    print(f"Errors: {total_errors}")
    print(f"Overall kill rate: {overall_rate:.1f}%")
    print()

    print("Per-module results:")
    print(f"{'Module':<35} {'Muts':>5} {'Kill':>5} {'Surv':>5} {'Rate':>6}")
    print("-" * 60)
    for mod, k, s, e, rate in sorted(results, key=lambda x: x[4]):
        print(f"{mod:<35} {k+s:>5} {k:>5} {s:>5} {rate:>5.0f}%")

    if all_survivors:
        print(f"\n--- SURVIVING MUTATIONS (oracle blind spots) ---")
        for mod, svs in all_survivors.items():
            print(f"\n  {mod}:")
            for sv in svs:
                print(f"    - {sv}")

    # Exit code: 0 if kill rate meets threshold, 1 otherwise
    threshold = args.threshold
    if overall_rate >= threshold:
        print(f"\nPASS: Kill rate {overall_rate:.1f}% >= {threshold}% threshold")
        sys.exit(0)
    else:
        print(f"\nFAIL: Kill rate {overall_rate:.1f}% < {threshold}% threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
