#!/usr/bin/env python3
"""bob-check: Run all validation (compile + test + lint) in one shot."""

import subprocess
import sys
import os
import time

# Resolve project paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIND_CLONE_DIR = os.path.dirname(SCRIPT_DIR)  # mind-clone/
ROOT_DIR = os.path.dirname(MIND_CLONE_DIR)     # ai-agent-platform/
SRC_DIR = os.path.join(MIND_CLONE_DIR, "src")


def run_step(name, cmd, cwd=None):
    """Run a command, return (passed, output, duration_ms)."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        passed = result.returncode == 0
        output = (result.stdout + result.stderr).strip()
        return passed, output, elapsed
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, "TIMEOUT (300s)", elapsed
    except FileNotFoundError:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, f"Command not found: {cmd[0]}", elapsed
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, str(e), elapsed


def main():
    print("=" * 60)
    print("  bob-check: Compile + Test + Lint")
    print("=" * 60)
    print()

    steps = [
        ("Compile", [sys.executable, "-m", "compileall", "-q", SRC_DIR], ROOT_DIR, True),
        ("Pytest", [sys.executable, "-m", "pytest", "--tb=short", "-q"], MIND_CLONE_DIR, True),
        ("Ruff", [sys.executable, "-m", "ruff", "check", SRC_DIR], ROOT_DIR, False),
    ]

    results = []
    for name, cmd, cwd, required in steps:
        print(f"  Running {name}...", end="", flush=True)
        passed, output, elapsed = run_step(name, cmd, cwd)

        # Detect missing optional tool
        is_missing = not passed and "No module named" in output
        if is_missing and not required:
            print(f" SKIP ({elapsed}ms) — not installed")
            results.append((name, True))  # Don't fail on missing optional tools
            continue

        mark = "PASS" if passed else "FAIL"
        print(f" {mark} ({elapsed}ms)")
        if not passed and output:
            # Show first 15 lines of failure output
            lines = output.split("\n")
            for line in lines[:15]:
                print(f"    {line}")
            if len(lines) > 15:
                print(f"    ... ({len(lines) - 15} more lines)")
            print()
        results.append((name, passed))

    print()
    print("-" * 60)
    all_passed = all(p for _, p in results)
    for name, passed in results:
        mark = "+" if passed else "x"
        print(f"  [{mark}] {name}")
    print()
    if all_passed:
        print("  OVERALL: PASS")
    else:
        failed = [n for n, p in results if not p]
        print(f"  OVERALL: FAIL ({', '.join(failed)})")
    print("-" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
