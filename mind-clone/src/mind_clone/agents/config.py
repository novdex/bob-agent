"""
Agent team configuration.

All settings for the autonomous agent team. Uses Bob's existing
config system where possible, adds agent-specific settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentConfig:
    """Configuration for the agent team."""

    # --- LLM settings ---
    api_key: str = ""
    base_url: str = "https://api.moonshot.ai/v1"
    model: str = "kimi-k2.5"
    max_tokens: int = 8192
    temperature: float = 1.0  # Kimi K2.5 requires exactly 1.0

    # --- Workspace ---
    repo_root: str = ""          # auto-detected
    branch_prefix: str = "agent/"  # branches created as agent/<task-slug>

    # --- Safety rails ---
    max_coder_retries: int = 3        # max times Coder retries after Reviewer/Tester rejection
    require_tests_pass: bool = True   # tests MUST pass before merge
    auto_revert_on_failure: bool = True  # revert self-modifications if tests fail
    protected_paths: List[str] = field(default_factory=lambda: [
        ".env",                  # secrets — never touch
        ".git/",                 # git internals
    ])

    # --- Agent behavior ---
    max_files_per_plan: int = 20      # planner won't modify more than this many files
    max_lines_per_change: int = 500   # coder won't write more than this many lines per file
    review_strictness: str = "normal"  # "lenient", "normal", "strict"

    # --- Logging ---
    log_agent_prompts: bool = True    # log all prompts/responses for debugging
    log_dir: str = "persist/agent_logs"

    def __post_init__(self):
        """Load from environment if not set explicitly."""
        if not self.api_key:
            self.api_key = os.environ.get("KIMI_API_KEY", "")
        if not self.repo_root:
            # Walk up from this file to find the mind-clone root
            current = os.path.dirname(os.path.abspath(__file__))
            for _ in range(5):
                if os.path.exists(os.path.join(current, "pyproject.toml")):
                    self.repo_root = current
                    break
                current = os.path.dirname(current)
        if not os.path.isabs(self.log_dir):
            self.log_dir = os.path.join(self.repo_root, self.log_dir)

    def is_protected(self, path: str) -> bool:
        """Check if a file path is protected from modification."""
        for protected in self.protected_paths:
            if path.startswith(protected) or path.endswith(protected):
                return True
        return False
