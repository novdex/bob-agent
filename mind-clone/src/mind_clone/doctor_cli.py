"""Run Bob Doctor from command line: python -m mind_clone.doctor_cli

Exit code 0 = all checks passed, 1 = at least one issue found.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Entry point for ``python -m mind_clone.doctor_cli``."""
    from mind_clone.services.doctor import run_doctor

    result = run_doctor()
    sys.exit(0 if result.get("all_ok") else 1)


if __name__ == "__main__":
    main()
