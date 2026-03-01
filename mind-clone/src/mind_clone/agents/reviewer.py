"""
Reviewer agent — checks code quality, security, and convention adherence.

Reads the Coder's output and either approves or rejects with specific feedback.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Any, List

from .llm_client import LLMClient
from .workspace import Workspace
from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.reviewer")

REVIEWER_SYSTEM = """You are the Reviewer agent in an autonomous code modification system.

Your job: review code changes and APPROVE or REJECT them.

CHECK FOR:
1. Bugs — logic errors, off-by-one, None checks, exception handling
2. Security — injection, path traversal, hardcoded secrets, unsafe eval
3. Convention violations — does it match existing code style?
4. Missing error handling — what happens when things fail?
5. Import issues — are all imports available?
6. Breaking changes — does this break existing functionality?
7. Test coverage — are new behaviors tested?

STRICTNESS LEVEL: {strictness}
- lenient: only reject for bugs and security issues
- normal: reject for bugs, security, and convention violations
- strict: reject for anything suboptimal

OUTPUT FORMAT — respond with ONLY valid JSON:
{{
  "approved": true|false,
  "issues": [
    {{
      "severity": "critical|warning|nit",
      "file": "path/to/file.py",
      "line": 42,
      "description": "what's wrong",
      "suggestion": "how to fix it"
    }}
  ],
  "summary": "overall assessment"
}}

IMPORTANT:
- If approved=false, issues MUST contain at least one critical item
- Be specific — vague feedback wastes everyone's time
- Don't reject for style preferences — only real problems"""


class Reviewer:
    """Reviews code changes for quality and correctness."""

    def __init__(self, llm: LLMClient, workspace: Workspace, config: AgentConfig):
        self.llm = llm
        self.workspace = workspace
        self.config = config

    def review_changes(
        self,
        plan: Dict[str, Any],
        coder_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Review all changes made by the Coder.

        Args:
            plan: The original plan
            coder_result: Result from Coder.execute_plan()

        Returns:
            {"approved": bool, "issues": [...], "summary": str}
        """
        files_modified = coder_result.get("files_modified", [])
        if not files_modified:
            return {"approved": True, "issues": [], "summary": "No files to review"}

        # Read current state of modified files
        file_contents = {}
        for fpath in files_modified:
            content = self.workspace.read_file(fpath)
            if content:
                file_contents[fpath] = content

        # Also get the diff
        diff = self.workspace.get_diff()

        system = REVIEWER_SYSTEM.format(strictness=self.config.review_strictness)

        prompt = self._build_review_prompt(plan, file_contents, diff)

        try:
            response = self.llm.ask(prompt, system=system, max_tokens=4096)
        except RuntimeError as e:
            # If LLM fails, default to cautious rejection
            return {
                "approved": False,
                "issues": [{"severity": "critical", "file": "", "line": 0,
                            "description": f"Review failed: {e}", "suggestion": "retry"}],
                "summary": f"LLM error during review: {e}",
            }

        review = self._parse_review(response)
        if not review:
            return {
                "approved": False,
                "issues": [{"severity": "critical", "file": "", "line": 0,
                            "description": "Could not parse review response",
                            "suggestion": "check LLM output"}],
                "summary": "Failed to parse review",
            }

        logger.info(
            "Reviewer: %s — %d issues found",
            "APPROVED" if review["approved"] else "REJECTED",
            len(review.get("issues", [])),
        )
        return review

    def _build_review_prompt(
        self,
        plan: Dict[str, Any],
        file_contents: Dict[str, str],
        diff: str,
    ) -> str:
        """Build the review prompt."""
        parts = [f"## Plan Summary\n{plan.get('summary', 'no summary')}"]

        parts.append("\n## Modified Files")
        for fpath, content in file_contents.items():
            # Truncate very large files
            truncated = content[:6000]
            parts.append(f"\n### {fpath}\n```python\n{truncated}\n```")

        if diff:
            parts.append(f"\n## Git Diff\n```diff\n{diff[:4000]}\n```")

        parts.append("\nReview these changes. Respond with ONLY valid JSON.")
        return "\n".join(parts)

    def _parse_review(self, response: str) -> Dict[str, Any]:
        """Extract JSON review from LLM response."""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        import re
        match = re.search(r"\{[\s\S]*\}", response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def get_rejection_feedback(self, review: Dict[str, Any]) -> str:
        """
        Format rejection feedback for the Coder to act on.

        Returns:
            Human-readable feedback string
        """
        lines = [f"REVIEW REJECTED: {review.get('summary', '')}"]
        for issue in review.get("issues", []):
            sev = issue.get("severity", "?").upper()
            desc = issue.get("description", "")
            suggestion = issue.get("suggestion", "")
            fpath = issue.get("file", "")
            line = issue.get("line", "")

            loc = f" ({fpath}:{line})" if fpath else ""
            lines.append(f"  [{sev}]{loc} {desc}")
            if suggestion:
                lines.append(f"    -> Fix: {suggestion}")

        return "\n".join(lines)
