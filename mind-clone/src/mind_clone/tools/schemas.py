"""
OpenAI function calling schemas for all tools.
"""

from __future__ import annotations

from typing import Dict, List, Any

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
        "description": "Open a URL in browser",
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
        "description": "Click an element",
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
        "description": "Type text into element",
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
        "description": "Take browser screenshot",
        "parameters": {
            "type": "object",
            "properties": {},
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
    BROWSER_CLOSE_SCHEMA,
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


# Alias for backward compatibility
TOOL_DEFINITIONS = ALL_TOOL_SCHEMAS

__all__ = [
    "ALL_TOOL_SCHEMAS",
    "TOOL_DEFINITIONS",
    "get_all_tool_schemas",
    "get_tool_schema_by_name",
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
    "CREATE_TASK_SCHEMA",
    "LIST_TASKS_SCHEMA",
    "GET_TASK_SCHEMA",
    "CANCEL_TASK_SCHEMA",
    "CREATE_GOAL_SCHEMA",
    "LIST_GOALS_SCHEMA",
    "BROWSER_OPEN_SCHEMA",
    "BROWSER_CLICK_SCHEMA",
    "BROWSER_TYPE_SCHEMA",
    "BROWSER_SCREENSHOT_SCHEMA",
    "BROWSER_EXECUTE_JS_SCHEMA",
    "BROWSER_NAVIGATE_SCHEMA",
    "BROWSER_CLOSE_SCHEMA",
]
