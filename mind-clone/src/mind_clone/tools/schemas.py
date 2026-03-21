"""
OpenAI function calling schemas for all tools.
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional

# Web & Research Tools
SEARCH_WEB_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web using DuckDuckGo",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results", "default": 5},
            },
            "required": ["query"],
        },
    },
}

READ_WEBPAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_webpage",
        "description": "Read and extract text from a webpage",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to read"},
            },
            "required": ["url"],
        },
    },
}

DEEP_RESEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "deep_research",
        "description": "Perform deep research on a topic",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Research topic"},
                "num_results": {"type": "integer", "description": "Number of sources", "default": 8},
            },
            "required": ["topic"],
        },
    },
}

# File Operations
READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read content from a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
            },
            "required": ["file_path"],
        },
    },
}

WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write content to a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append mode", "default": False},
            },
            "required": ["file_path", "content"],
        },
    },
}

LIST_DIRECTORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "List directory contents",
        "parameters": {
            "type": "object",
            "properties": {
                "dir_path": {"type": "string", "description": "Directory path", "default": "."},
            },
        },
    },
}

# Code Execution
RUN_COMMAND_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": "Run a shell command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "timeout": {"type": "integer", "description": "Timeout seconds", "default": 30},
            },
            "required": ["command"],
        },
    },
}

EXECUTE_PYTHON_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_python",
        "description": "Execute Python code",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "timeout": {"type": "integer", "description": "Timeout seconds", "default": 15},
            },
            "required": ["code"],
        },
    },
}

# Memory Tools
SAVE_RESEARCH_NOTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_research_note",
        "description": "Save a research note",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Note topic"},
                "summary": {"type": "string", "description": "Note summary"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "Source URLs"},
            },
            "required": ["topic", "summary"],
        },
    },
}

RESEARCH_MEMORY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "research_memory_search",
        "description": "Search research notes",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
}

SEMANTIC_MEMORY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "semantic_memory_search",
        "description": "Semantic search in memory",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
}

# Communication
SEND_EMAIL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "Send an email",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
}

# Task Management
CREATE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a new task",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "goal": {"type": "string", "description": "Task goal/description"},
            },
            "required": ["title", "goal"],
        },
    },
}

LIST_TASKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "List recent tasks",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
}

# Browser Tools
BROWSER_OPEN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_open",
        "description": "Open a URL in a headless Chromium browser session. Returns page title and a structural snapshot of the DOM.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open"},
                "headless": {"type": "boolean", "default": False},
            },
            "required": ["url"],
        },
    },
}

BROWSER_GET_TEXT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_get_text",
        "description": "Get text from page element",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector", "default": "body"},
            },
        },
    },
}

BROWSER_CLICK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_click",
        "description": "Click a page element identified by CSS selector. Waits for the element to be visible before clicking.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
            },
            "required": ["selector"],
        },
    },
}

BROWSER_TYPE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_type",
        "description": "Type text into a form input or other editable element identified by CSS selector. Optionally press Enter to submit.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
    },
}

BROWSER_SCREENSHOT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_screenshot",
        "description": "Capture a screenshot of the current browser page. Returns the file path to the saved PNG image.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


BROWSER_EXECUTE_JS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_execute_js",
        "description": "Execute JavaScript code in the browser page context and return the result. Requires browser_open first.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "JavaScript code to execute in the browser page. Supports any valid JS expression. The result of the last expression is returned. Requires browser_open first."},
            },
            "required": ["code"],
        },
    },
}

BROWSER_CLOSE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_close",
        "description": "Close browser session",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

# Agent team tools
AGENT_TEAM_RUN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "agent_team_run",
        "description": (
            "Launch the autonomous agent team to modify the codebase. "
            "Provide a task description and the team (Planner, Coder, Reviewer, Tester) "
            "will create a branch, make changes, run tests, and merge if everything passes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Description of the code change to make (max 2000 chars)",
                },
            },
            "required": ["task"],
        },
    },
}

AGENT_TEAM_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "agent_team_status",
        "description": "Check the current status of the agent team — running, idle, or errored.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# All tool schemas
ALL_TOOL_SCHEMAS = [
    SEARCH_WEB_SCHEMA,
    READ_WEBPAGE_SCHEMA,
    DEEP_RESEARCH_SCHEMA,
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    LIST_DIRECTORY_SCHEMA,
    RUN_COMMAND_SCHEMA,
    EXECUTE_PYTHON_SCHEMA,
    SAVE_RESEARCH_NOTE_SCHEMA,
    RESEARCH_MEMORY_SEARCH_SCHEMA,
    SEMANTIC_MEMORY_SEARCH_SCHEMA,
    SEND_EMAIL_SCHEMA,
    CREATE_TASK_SCHEMA,
    LIST_TASKS_SCHEMA,
    # Scheduler — MUST be visible so Bob can create proactive jobs
    {
        "type": "function",
        "function": {
            "name": "schedule_job",
            "description": (
                "Schedule a recurring job that runs automatically and sends results to the user's Telegram. "
                "USE THIS when the user asks to be pinged, notified, or updated about anything on a schedule "
                "(e.g. 'tell me about X every 5 minutes', 'ping me with news hourly', 'remind me about Y'). "
                "The job message is processed by you (Bob) and the result is automatically sent to Telegram. "
                "You CAN proactively send messages — use this tool to set it up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Short job name (e.g. 'ai_news_5min', 'iran_updates')",
                    },
                    "message": {
                        "type": "string",
                        "description": "What you (Bob) should do each time the job fires — e.g. 'Search for latest AI news and summarise in 5 bullet points'",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "How often to run in seconds. 300=5min, 3600=1hr, 86400=1day",
                    },
                },
                "required": ["name", "message", "interval_seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_jobs",
            "description": "List all currently scheduled recurring jobs.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disable_scheduled_job",
            "description": "Disable/cancel a scheduled job by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "integer", "description": "ID of the job to disable"},
                },
                "required": ["job_id"],
            },
        },
    },
    BROWSER_OPEN_SCHEMA,
    BROWSER_GET_TEXT_SCHEMA,
    BROWSER_CLICK_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    BROWSER_SCREENSHOT_SCHEMA,
    BROWSER_EXECUTE_JS_SCHEMA,
    BROWSER_CLOSE_SCHEMA,
    AGENT_TEAM_RUN_SCHEMA,
    AGENT_TEAM_STATUS_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "self_improve",
            "description": (
                "Attempt to fix Bob's own code based on the top open self-improvement opportunity. "
                "Bob reads his improvement notes, finds the relevant code, patches it, runs tests, "
                "and commits the fix. Use when asked to improve yourself or fix known issues."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_patterns",
            "description": (
                "Get Arsh's conversation patterns — recurring topics, interests, and what he "
                "asks about most. Use when asked about what Arsh cares about, to be more "
                "proactive, or when deciding what to monitor automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_retro",
            "description": (
                "Run Bob's self-awareness retro. Collects stats from the last 24h "
                "(messages, tool usage, failures, corrections, episodes), "
                "generates an analysis via LLM, saves a SelfImprovementNote, "
                "and optionally sends the report to Telegram. "
                "Use when asked to reflect, run retro, or review performance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "send_to_telegram": {
                        "type": "boolean",
                        "description": "Send the retro report to Telegram (default true)",
                    },
                },
                "required": [],
            },
        },
    },
]


SKILL_LIBRARY_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": (
                "Save a completed task as a reusable skill in Bob's Voyager-style skill library. "
                "Call this AFTER successfully completing any non-trivial task so Bob can reuse "
                "the approach next time. Include step-by-step instructions in the body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short descriptive name for this skill"},
                    "body": {"type": "string", "description": "Step-by-step instructions that worked"},
                    "trigger_hints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords/phrases that should trigger this skill in future",
                    },
                    "intent": {"type": "string", "description": "One-sentence description of what this skill does"},
                    "skill_key": {"type": "string", "description": "Optional unique key (auto-generated if omitted)"},
                },
                "required": ["title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_skill",
            "description": (
                "Search Bob's skill library for relevant past approaches before starting a task. "
                "Call this at the START of complex tasks — Bob may have solved something similar before."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Description of the task you're about to do"},
                    "top_k": {"type": "integer", "description": "Max skills to return (default 3)", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all skills in Bob's library with titles, usage counts, and trigger hints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter: 'active', 'archived', or 'all' (default: active)",
                        "enum": ["active", "archived", "all"],
                    },
                    "limit": {"type": "integer", "description": "Max to return (default 20)", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill",
            "description": "Get full details of a specific skill including its complete instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer", "description": "The numeric ID of the skill"},
                },
                "required": ["skill_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "archive_skill",
            "description": "Archive a skill so it no longer gets auto-matched (kept in history).",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer", "description": "The numeric ID of the skill to archive"},
                },
                "required": ["skill_id"],
            },
        },
    },
]

ALL_TOOL_SCHEMAS.extend(SKILL_LIBRARY_SCHEMAS)

# Memory graph schemas (A-MEM / MAGMA / Zettelkasten)
_MEMORY_GRAPH_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "link_memories",
            "description": "Create a directed graph link between two memory nodes. Use to explicitly connect related memories (research notes, skills, improvement notes, episodes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "src_type": {"type": "string", "enum": ["research_note", "episodic", "improvement", "skill"], "description": "Source node type"},
                    "src_id": {"type": "integer", "description": "Source node ID"},
                    "tgt_type": {"type": "string", "enum": ["research_note", "episodic", "improvement", "skill"], "description": "Target node type"},
                    "tgt_id": {"type": "integer", "description": "Target node ID"},
                    "relation": {"type": "string", "enum": ["related", "supports", "contradicts", "evolved_from", "caused_by", "learned_from"], "description": "Type of relationship", "default": "related"},
                    "note": {"type": "string", "description": "Optional note explaining the connection"},
                },
                "required": ["src_type", "src_id", "tgt_type", "tgt_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_graph_search",
            "description": "Traverse Bob's memory graph from a starting node to discover related memories. Returns all connected nodes within the given depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_type": {"type": "string", "enum": ["research_note", "episodic", "improvement", "skill"], "description": "Starting node type"},
                    "start_id": {"type": "integer", "description": "Starting node ID"},
                    "depth": {"type": "integer", "description": "How many hops to traverse (default 2, max 3)", "default": 2},
                    "max_nodes": {"type": "integer", "description": "Max nodes to return (default 10)", "default": 10},
                },
                "required": ["start_type", "start_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_link_memory",
            "description": "Automatically find and link related memories to a given node using keyword overlap (Zettelkasten style). Call this after saving a new research note or skill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src_type": {"type": "string", "enum": ["research_note", "episodic", "improvement", "skill"], "description": "Node type to auto-link"},
                    "src_id": {"type": "integer", "description": "Node ID to auto-link"},
                    "min_overlap": {"type": "integer", "description": "Minimum keyword overlap to create a link (default 2)", "default": 2},
                },
                "required": ["src_type", "src_id"],
            },
        },
    },
]
ALL_TOOL_SCHEMAS.extend(_MEMORY_GRAPH_SCHEMAS)

# DSPy + CORPGEN schemas
ALL_TOOL_SCHEMAS.extend([
    {"type":"function","function":{"name":"browse_and_extract","description":"Navigate to a URL and extract information matching a goal using browser automation.","parameters":{"type":"object","properties":{"url":{"type":"string"},"goal":{"type":"string","default":"extract all important information"}},"required":["url"]}}},
    {"type":"function","function":{"name":"rag_search","description":"Semantic search across Bob's knowledge base using vector embeddings.","parameters":{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":5},"doc_type":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"rag_ingest","description":"Index all ResearchNotes into the semantic knowledge base for vector search.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"rag_store","description":"Store a document or text in the knowledge base with vector embedding.","parameters":{"type":"object","properties":{"text":{"type":"string"},"doc_type":{"type":"string","default":"document"}},"required":["text"]}}},
    {"type":"function","function":{"name":"spawn_agents","description":"Spawn multiple sub-agents to run tasks in parallel. Provide a goal (auto-decomposed) or explicit task list.","parameters":{"type":"object","properties":{"goal":{"type":"string","description":"High-level goal to decompose into parallel tasks"},"tasks":{"type":"array","items":{"type":"object"}}},"required":[]}}},
    {"type":"function","function":{"name":"run_learning","description":"Run a continuous learning cycle: learn from arXiv, GitHub trending, and tech news.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"sandbox_python","description":"Run Python code in an isolated sandbox with timeout. Safe execution.","parameters":{"type":"object","properties":{"code":{"type":"string"},"timeout":{"type":"integer","default":15},"inputs":{"type":"object"}},"required":["code"]}}},
    {"type":"function","function":{"name":"sandbox_shell","description":"Run a shell command in a sandbox with timeout.","parameters":{"type":"object","properties":{"command":{"type":"string"},"timeout":{"type":"integer","default":10}},"required":["command"]}}},
    {"type":"function","function":{"name":"speak","description":"Convert text to speech and send as a voice message to Telegram.","parameters":{"type":"object","properties":{"text":{"type":"string"},"send_to_telegram":{"type":"boolean","default":True}},"required":["text"]}}},
    {"type":"function","function":{"name":"get_calendar","description":"Get upcoming calendar events (requires GOOGLE_CALENDAR_KEY in .env).","parameters":{"type":"object","properties":{"hours_ahead":{"type":"integer","default":24}},"required":[]}}},
    {"type":"function","function":{"name":"create_reminder","description":"Create a reminder at a specific time.","parameters":{"type":"object","properties":{"title":{"type":"string"},"at":{"type":"string","description":"Time like '09:00' or '2026-03-21 09:00'"}},"required":["title","at"]}}},
    {"type":"function","function":{"name":"dashboard","description":"Get Bob's full observability dashboard: tool success rates, experiment history, memory stats, scheduled jobs.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"auto_merge","description":"Attempt to auto-merge agent/test → main if experiments show consistent improvement and all tests pass.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"check_merge","description":"Check if agent/test branch is ready to merge to main.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"store_teaching_moment","description":"Store a high-quality exchange as a teaching moment for future Bob to learn from.","parameters":{"type":"object","properties":{"user_message":{"type":"string"},"response":{"type":"string"}},"required":["user_message","response"]}}},
])

ALL_TOOL_SCHEMAS.extend([
    {"type":"function","function":{"name":"get_user_profile","description":"Get the current user profile (interests, style, projects).","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"update_user_profile","description":"Update a field in the user profile.","parameters":{"type":"object","properties":{"field":{"type":"string"},"value":{}},"required":["field","value"]}}},
    {"type":"function","function":{"name":"run_briefing","description":"Run the morning research briefing now — research user interests and send to Telegram.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"run_self_tests","description":"Run Bob's test suite and return pass/fail results.","parameters":{"type":"object","properties":{"test_file":{"type":"string","description":"Optional specific test file path"}},"required":[]}}},
    {"type":"function","function":{"name":"generate_tests","description":"Generate pytest tests for a service file.","parameters":{"type":"object","properties":{"service_name":{"type":"string"},"service_file":{"type":"string"}},"required":["service_name","service_file"]}}},
    {"type":"function","function":{"name":"get_world_model","description":"Get Bob's current world model (projects, events, predictions).","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"update_world","description":"Update a field in Bob's world model.","parameters":{"type":"object","properties":{"section":{"type":"string"},"key":{"type":"string"},"value":{}},"required":["section","key","value"]}}},
    {"type":"function","function":{"name":"meta_research","description":"Meta-tool: search + read pages + summarise + save as ResearchNote in one call.","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"meta_report","description":"Meta-tool: multi-source search + compile into structured report in one call.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"meta_run","description":"Meta-tool: run shell command + check output + return structured result.","parameters":{"type":"object","properties":{"command":{"type":"string"},"expect_success":{"type":"boolean","default":True}},"required":["command"]}}},
])

ALL_TOOL_SCHEMAS.extend([
    {
        "type": "function",
        "function": {
            "name": "research_github",
            "description": "Search GitHub for top repos on a topic, read READMEs, extract key insights, and save as ResearchNotes linked in the knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to research on GitHub"},
                    "save_notes": {"type": "boolean", "description": "Save findings as ResearchNotes (default true)", "default": True},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forge_tool",
            "description": "Synthesize and register a new Python tool on the fly when you discover a capability gap. Use when you can't do something and need a new tool right now.",
            "parameters": {
                "type": "object",
                "properties": {
                    "capability": {"type": "string", "description": "What capability the new tool needs to provide"},
                    "tool_name": {"type": "string", "description": "Name for the new tool (snake_case)"},
                },
                "required": ["capability"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evolve_critic",
            "description": "Evolve the co-critic's principles based on real failure history. Run weekly to keep the critic sharp as Bob improves.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_triggers",
            "description": "Scan event triggers: error spikes, stale experiments, memory bloat, degraded tools. Returns list of events that need attention.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_decay",
            "description": "Run Ebbinghaus memory decay: fades unimportant old memories, boosts recalled ones, prunes noise. Run daily for healthy memory hygiene.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimise_prompts",
            "description": "Run DSPy-style automatic prompt optimisation. Analyses which tools are failing and rewrites their usage hints to improve success rates. Run weekly or when tools seem to be underperforming.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_isolated_task",
            "description": "Run a specific sub-task in a completely isolated context to prevent memory contamination with other tasks. Use when handling complex multi-part requests.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The specific sub-task to execute in isolation"},
                    "context": {"type": "string", "description": "Essential context from the parent task (keep minimal)"},
                    "tools_allowed": {"type": "array", "items": {"type": "string"}, "description": "Optional list of tool names to allow (defaults to all)"},
                },
                "required": ["task"],
            },
        },
    },
])

# Karpathy experiment loop schema
ALL_TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "run_experiment",
        "description": (
            "Run Bob's Karpathy-style autonomous self-improvement experiment loop. "
            "Bob will read his own codebase, generate a hypothesis, implement a small change, "
            "run tests, measure the composite score, and keep the change if it improved things "
            "or revert it if not. Results are saved to ExperimentLog and reported via Telegram."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Get all tool schemas."""
    return list(ALL_TOOL_SCHEMAS)


def get_tool_schema_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get a specific tool schema by name."""
    for schema in ALL_TOOL_SCHEMAS:
        if schema["function"]["name"] == name:
            return schema
    return None


def validate_schemas() -> bool:
    """Validate all schemas have required keys: type, function with name+description+parameters.

    Returns True if all schemas are valid, False otherwise.
    """
    import logging
    logger = logging.getLogger("mind_clone.tools.schemas")

    for idx, schema in enumerate(ALL_TOOL_SCHEMAS):
        if "type" not in schema or schema["type"] != "function":
            logger.error("SCHEMA_VALIDATION_FAIL index=%d missing_type_or_not_function", idx)
            return False
        if "function" not in schema:
            logger.error("SCHEMA_VALIDATION_FAIL index=%d missing_function", idx)
            return False

        func = schema["function"]
        if "name" not in func or not func.get("name"):
            logger.error("SCHEMA_VALIDATION_FAIL index=%d missing_function_name", idx)
            return False
        if "description" not in func or not func.get("description"):
            logger.error("SCHEMA_VALIDATION_FAIL index=%d missing_function_description", idx)
            return False
        if "parameters" not in func:
            logger.error("SCHEMA_VALIDATION_FAIL index=%d missing_parameters", idx)
            return False

    logger.info("SCHEMA_VALIDATION_OK schemas=%d", len(ALL_TOOL_SCHEMAS))
    return True


def get_required_params(schema_name: str) -> List[str]:
    """Get list of required parameter names for a schema.

    Args:
        schema_name: Name of the tool schema (e.g. 'search_web')

    Returns:
        List of required parameter names, empty list if schema not found.
    """
    schema = get_tool_schema_by_name(schema_name)
    if not schema:
        return []

    params = schema.get("function", {}).get("parameters", {})
    return params.get("required", [])


def get_all_schema_names() -> List[str]:
    """Get sorted list of all schema names."""
    return sorted([s["function"]["name"] for s in ALL_TOOL_SCHEMAS])


# Alias for backward compatibility
TOOL_DEFINITIONS = ALL_TOOL_SCHEMAS

__all__ = [
    "ALL_TOOL_SCHEMAS",
    "TOOL_DEFINITIONS",
    "get_tool_schemas",
    "get_tool_schema_by_name",
    "validate_schemas",
    "get_required_params",
    "get_all_schema_names",
    "SEARCH_WEB_SCHEMA",
    "READ_WEBPAGE_SCHEMA",
    "DEEP_RESEARCH_SCHEMA",
    "READ_FILE_SCHEMA",
    "WRITE_FILE_SCHEMA",
    "LIST_DIRECTORY_SCHEMA",
    "RUN_COMMAND_SCHEMA",
    "EXECUTE_PYTHON_SCHEMA",
    "SEND_EMAIL_SCHEMA",
    "SAVE_RESEARCH_NOTE_SCHEMA",
    "RESEARCH_MEMORY_SEARCH_SCHEMA",
    "SEMANTIC_MEMORY_SEARCH_SCHEMA",
    "BROWSER_OPEN_SCHEMA",
    "BROWSER_GET_TEXT_SCHEMA",
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_TYPE_SCHEMA",
    "BROWSER_SCREENSHOT_SCHEMA",
    "BROWSER_EXECUTE_JS_SCHEMA",
    "BROWSER_CLOSE_SCHEMA",
]
