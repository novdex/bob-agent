"""
Coder agent — writes code changes following the Planner's plan.

Takes a plan with specific steps and produces actual file modifications.
Writes one file at a time, following existing codebase conventions.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Any, List

from .llm_client import LLMClient
from .workspace import Workspace
from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.coder")

CODER_SYSTEM = """You are the Coder agent in an autonomous code modification system.

Your job: given a specific instruction for ONE file, write the COMPLETE updated file content.

RULES:
1. Output ONLY the file content — no explanations, no markdown fences, no commentary
2. Match the existing code style exactly (indentation, naming, imports)
3. Keep changes minimal — only modify what the plan says
4. Preserve all existing functionality unless explicitly told to remove it
5. Add docstrings to new functions
6. Follow Python best practices (type hints, error handling)
7. Max {max_lines} lines per file

If creating a NEW file, write the complete file.
If MODIFYING an existing file, write the COMPLETE updated file (not a diff).

Output the raw file content directly. No wrapping, no code blocks, no explanation."""

CODER_SYSTEM_DIFF = """You are the Coder agent in an autonomous code modification system.

Your job: given a specific instruction for ONE file, produce a precise diff.

RULES:
1. Output a JSON object with the changes
2. Each change specifies old_text (exact text to find) and new_text (replacement)
3. old_text must be unique in the file — include enough context
4. Keep changes minimal

OUTPUT FORMAT — respond with ONLY valid JSON:
{{
  "file": "path/to/file.py",
  "changes": [
    {{
      "old_text": "exact text to replace (including surrounding context for uniqueness)",
      "new_text": "replacement text"
    }}
  ]
}}
"""


class Coder:
    """Writes code changes following plans."""

    def __init__(self, llm: LLMClient, workspace: Workspace, config: AgentConfig):
        self.llm = llm
        self.workspace = workspace
        self.config = config

    def execute_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute all steps in a plan.

        Args:
            plan: Plan from the Planner agent

        Returns:
            {"ok": bool, "changes": [...], "error": str}
        """
        steps = plan.get("steps", [])
        if not steps:
            return {"ok": False, "error": "Plan has no steps"}

        changes = []
        errors = []

        for step in steps:
            result = self._execute_step(step)
            if result["ok"]:
                changes.append(result)
            else:
                errors.append(f"Step {step.get('step', '?')}: {result['error']}")
                # Continue with other steps — don't fail everything

        if not changes and errors:
            return {"ok": False, "error": "; ".join(errors), "changes": []}

        return {
            "ok": True,
            "changes": changes,
            "errors": errors,
            "files_modified": [c["file"] for c in changes],
        }

    def _execute_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single plan step."""
        fpath = step.get("file", "")
        action = step.get("action", "modify")
        description = step.get("description", "")
        details = step.get("details", "")

        logger.info("Coder: %s %s — %s", action, fpath, description[:80])

        if self.config.is_protected(fpath):
            return {"ok": False, "file": fpath, "error": "Protected file"}

        if action == "delete":
            return self._delete_file(fpath)
        elif action == "create":
            return self._create_file(fpath, description, details)
        elif action == "modify":
            return self._modify_file(fpath, description, details)
        else:
            return {"ok": False, "file": fpath, "error": f"Unknown action: {action}"}

    def _create_file(self, fpath: str, description: str, details: str) -> Dict[str, Any]:
        """Create a new file."""
        system = CODER_SYSTEM.format(max_lines=self.config.max_lines_per_change)

        prompt = f"""Create a new file: {fpath}

## What this file should do
{description}

## Specific instructions
{details}

Write the COMPLETE file content. No markdown fences, no explanation — just the raw file."""

        try:
            content = self.llm.ask(prompt, system=system, max_tokens=self.config.max_tokens)
        except RuntimeError as e:
            return {"ok": False, "file": fpath, "error": str(e)}

        # Strip any accidental markdown fences
        content = self._strip_fences(content)

        if self.workspace.write_file(fpath, content):
            return {"ok": True, "file": fpath, "action": "create", "lines": content.count("\n") + 1}
        return {"ok": False, "file": fpath, "error": "Failed to write file"}

    def _modify_file(self, fpath: str, description: str, details: str) -> Dict[str, Any]:
        """Modify an existing file."""
        current = self.workspace.read_file(fpath)
        if current is None:
            # File doesn't exist — treat as create
            return self._create_file(fpath, description, details)

        system = CODER_SYSTEM.format(max_lines=self.config.max_lines_per_change)

        prompt = f"""Modify this file: {fpath}

## Current file content
```python
{current[:8000]}
```

## What to change
{description}

## Specific instructions
{details}

Write the COMPLETE updated file. Include ALL existing code (modified as needed).
No markdown fences, no explanation — just the raw file."""

        try:
            content = self.llm.ask(prompt, system=system, max_tokens=self.config.max_tokens)
        except RuntimeError as e:
            return {"ok": False, "file": fpath, "error": str(e)}

        content = self._strip_fences(content)

        if self.workspace.write_file(fpath, content):
            return {"ok": True, "file": fpath, "action": "modify", "lines": content.count("\n") + 1}
        return {"ok": False, "file": fpath, "error": "Failed to write file"}

    def _delete_file(self, fpath: str) -> Dict[str, Any]:
        """Delete a file."""
        full = self.workspace.root / fpath
        if not full.exists():
            return {"ok": True, "file": fpath, "action": "delete", "note": "already absent"}
        try:
            full.unlink()
            return {"ok": True, "file": fpath, "action": "delete"}
        except Exception as e:
            return {"ok": False, "file": fpath, "error": str(e)}

    def _strip_fences(self, content: str) -> str:
        """Remove markdown code fences if the LLM wrapped its output."""
        lines = content.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)

    def apply_review_feedback(
        self, step: Dict[str, Any], feedback: str
    ) -> Dict[str, Any]:
        """
        Re-execute a step incorporating Reviewer feedback.

        Args:
            step: The original plan step
            feedback: Reviewer's rejection reason

        Returns:
            Same as _execute_step
        """
        fpath = step.get("file", "")
        current = self.workspace.read_file(fpath)
        description = step.get("description", "")
        details = step.get("details", "")

        system = CODER_SYSTEM.format(max_lines=self.config.max_lines_per_change)

        prompt = f"""Fix this file based on review feedback: {fpath}

## Current file content
```python
{current[:8000] if current else '(file not found)'}
```

## Original task
{description}
{details}

## Reviewer feedback (MUST address all points)
{feedback}

Write the COMPLETE fixed file. No markdown fences, no explanation — just the raw file."""

        try:
            content = self.llm.ask(prompt, system=system, max_tokens=self.config.max_tokens)
        except RuntimeError as e:
            return {"ok": False, "file": fpath, "error": str(e)}

        content = self._strip_fences(content)

        if self.workspace.write_file(fpath, content):
            return {"ok": True, "file": fpath, "action": "fix", "lines": content.count("\n") + 1}
        return {"ok": False, "file": fpath, "error": "Failed to write file"}
