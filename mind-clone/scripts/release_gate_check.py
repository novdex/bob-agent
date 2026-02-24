from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

# Ensure the modular package is importable
sys.path.insert(0, str(ROOT_DIR / "src"))


def main() -> int:
    from mind_clone.database import init_db
    from mind_clone.core.state import EVAL_MAX_CASES
    from mind_clone.agent.loop import evaluate_release_gate

    init_db()
    result = evaluate_release_gate(run_eval=True, max_cases=min(16, int(EVAL_MAX_CASES)))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if bool(result.get("ok", False)) else 1


if __name__ == "__main__":
    sys.exit(main())
