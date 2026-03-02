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
    BROWSER_OPEN_SCHEMA,
    BROWSER_GET_TEXT_SCHEMA,
    BROWSER_CLICK_SCHEMA,
    BROWSER_TYPE_SCHEMA,
    BROWSER_SCREENSHOT_SCHEMA,
    BROWSER_EXECUTE_JS_SCHEMA,
    BROWSER_CLOSE_SCHEMA,
    AGENT_TEAM_RUN_SCHEMA,
    AGENT_TEAM_STATUS_SCHEMA,
]


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
