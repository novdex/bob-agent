"""
Agent Team — autonomous code modification system.

Five specialized agents coordinated by an orchestrator:
  - Planner:      reads codebase, creates step-by-step plan
  - Coder:        writes code changes following the plan
  - Reviewer:     checks code quality, security, conventions
  - Tester:       runs pytest, coverage, mutation tests
  - Orchestrator: coordinates the pipeline end-to-end
"""

from .orchestrator import Orchestrator

__all__ = ["Orchestrator"]
