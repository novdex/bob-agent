"""
Planner agent — reads the codebase and creates a step-by-step plan.

Given a task description, the Planner:
1. Identifies which files are relevant
2. Reads those files to understand current code
3. Creates a structured plan with specific file changes
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Any, List, Optional

from .llm_client import LLMClient
from .workspace import Workspace
from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.planner")

PLANNER_SYSTEM = """You are the Planner agent in an autonomous code modification system.

Your job: given a task description and relevant source code, produce a PRECISE plan
for what files to modify and what changes to make.

RULES:
1. Be specific — name exact files, functions, line ranges
2. Keep changes minimal — do NOT refactor unrelated code
3. Respect existing patterns — match the codebase style
4. Consider test impact — if you change behavior, tests need updating
5. Never modify .env files or git internals
6. Max {max_files} files per plan

OUTPUT FORMAT — respond with ONLY valid JSON:
{{
  "summary": "one-line description of what this plan does",
  "files_to_read": ["path/to/file1.py", "path/to/file2.py"],
  "steps": [
    {{
      "step": 1,
      "file": "path/to/file.py",
      "action": "modify|create|delete",
      "description": "what to change and why",
      "details": "specific instructions for the Coder"
    }}
  ],
  "test_files": ["tests/to/create_or_modify.py"],
  "risk_level": "low|medium|high",
  "risk_notes": "what could go wrong"
}}
"""


class Planner:
    """Reads codebase and produces modification plans."""

    def __init__(self, llm: LLMClient, workspace: Workspace, config: AgentConfig):
        self.llm = llm
        self.workspace = workspace
        self.config = config

    def _gather_context(self, task: str) -> str:
        """Build a context string with project structure and key files."""
        lines = ["## Project Structure\n"]

        # Get all Python source files
        src_files = self.workspace.list_files("src/**/*.py")
        test_files = self.workspace.list_files("tests/**/*.py")

        lines.append("### Source files:")
        for f in src_files[:60]:
            lines.append(f"  - {f}")

        lines.append("\n### Test files:")
        for f in test_files[:40]:
            lines.append(f"  - {f}")

        # Read key architecture docs
        for doc in ["CLAUDE.md", "docs/AGENTS.md", "docs/VISION.md"]:
            content = self.workspace.read_file(doc)
            if content:
                # Truncate to avoid blowing context
                lines.append(f"\n## {doc}\n{content[:3000]}")

        return "\n".join(lines)

    def create_plan(self, task: str) -> Dict[str, Any]:
        """
        Create a modification plan for a task.

        Args:
            task: Natural language description of what to do

        Returns:
            Plan dictionary with steps, or error dict
        """
        logger.info("Planner: creating plan for task: %s", task[:100])

        # Phase 1: Gather context and ask LLM which files to read
        context = self._gather_context(task)
        system = PLANNER_SYSTEM.format(max_files=self.config.max_files_per_plan)

        prompt = f"""## Task
{task}

{context}

Create a precise modification plan. Respond with ONLY valid JSON."""

        try:
            response = self.llm.ask(prompt, system=system, max_tokens=4096)
        except RuntimeError as e:
            return {"ok": False, "error": f"LLM call failed: {e}"}

        # Parse JSON from response
        plan = self._parse_plan(response)
        if not plan:
            return {"ok": False, "error": "Failed to parse plan from LLM response", "raw": response[:500]}

        # Phase 2: Read the files the plan references and refine
        enriched_plan = self._enrich_plan(plan, task, system)

        # Validate the plan
        errors = self._validate_plan(enriched_plan)
        if errors:
            return {"ok": False, "error": f"Plan validation failed: {'; '.join(errors)}", "plan": enriched_plan}

        enriched_plan["ok"] = True
        logger.info("Planner: plan created with %d steps", len(enriched_plan.get("steps", [])))
        return enriched_plan

    def _parse_plan(self, response: str) -> Optional[Dict]:
        """Extract JSON plan from LLM response."""
        # Try direct parse first
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block in response
        import re
        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def _enrich_plan(self, plan: Dict, task: str, system: str) -> Dict:
        """Read the referenced files and refine the plan."""
        files_content = {}
        for step in plan.get("steps", []):
            fpath = step.get("file", "")
            if fpath and fpath not in files_content:
                content = self.workspace.read_file(fpath)
                if content:
                    # Truncate large files
                    files_content[fpath] = content[:5000]

        # Also read any files listed in files_to_read
        for fpath in plan.get("files_to_read", []):
            if fpath not in files_content:
                content = self.workspace.read_file(fpath)
                if content:
                    files_content[fpath] = content[:5000]

        if not files_content:
            return plan

        # Ask LLM to refine the plan with actual file contents
        file_context = "\n\n".join(
            f"### {path}\n```python\n{content}\n```"
            for path, content in files_content.items()
        )

        refine_prompt = f"""## Task
{task}

## Current Plan
{json.dumps(plan, indent=2)}

## Actual File Contents
{file_context}

Now that you can see the actual code, refine the plan. Fix any incorrect assumptions.
Respond with ONLY the updated JSON plan (same format)."""

        try:
            response = self.llm.ask(refine_prompt, system=system, max_tokens=4096)
            refined = self._parse_plan(response)
            if refined:
                return refined
        except RuntimeError:
            pass

        return plan

    def _validate_plan(self, plan: Dict) -> List[str]:
        """Validate a plan for safety issues."""
        errors = []
        steps = plan.get("steps", [])

        if not steps:
            errors.append("Plan has no steps")

        if len(steps) > self.config.max_files_per_plan:
            errors.append(f"Plan modifies {len(steps)} files (max {self.config.max_files_per_plan})")

        for step in steps:
            fpath = step.get("file", "")
            if self.config.is_protected(fpath):
                errors.append(f"Plan modifies protected file: {fpath}")

        return errors
