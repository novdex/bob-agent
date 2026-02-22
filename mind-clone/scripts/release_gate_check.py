from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "mind_clone_agent.py"


def load_module():
    spec = importlib.util.spec_from_file_location("mind_clone_agent_release_gate", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module()
    module.init_db()
    result = module.evaluate_release_gate(run_eval=True, max_cases=min(16, int(module.EVAL_MAX_CASES)))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if bool(result.get("ok", False)) else 1


if __name__ == "__main__":
    sys.exit(main())
