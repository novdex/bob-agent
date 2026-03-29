"""
MCP Client — Connect Bob to external MCP servers.

Bob can discover and call tools from any MCP server (Gmail, Calendar,
Notion, Slack, GitHub, etc.) using the Model Context Protocol.

MCP Protocol: JSON-RPC 2.0 over stdio or HTTP.
Spec: https://spec.modelcontextprotocol.io/

Two transport modes:
  - stdio: Launch a subprocess, communicate via stdin/stdout
  - http: Connect to an HTTP endpoint
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("mind_clone.mcp_client")

MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class MCPServer:
    """Configuration for an MCP server connection."""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    enabled: bool = True
    tools: List[Dict[str, Any]] = field(default_factory=list)
    connected: bool = False
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _request_id: int = field(default=0, repr=False)


class MCPClientManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self) -> None:
        self.servers: Dict[str, MCPServer] = {}
        self._tool_map: Dict[str, str] = {}  # tool_name -> server_name

    def register_server(self, server: MCPServer) -> None:
        """Register an MCP server configuration."""
        self.servers[server.name] = server
        logger.info("MCP_SERVER_REGISTERED name=%s transport=%s", server.name, server.transport)

    def load_config_from_json(self, config_path: str) -> int:
        """Load MCP server configurations from a JSON file.

        Expected format (same as Claude Desktop / Claude Code):
        {
            "mcpServers": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
                }
            }
        }
        """
        try:
            path = Path(config_path)
            if not path.exists():
                return 0
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", data.get("servers", {}))
            count = 0
            for name, cfg in servers.items():
                transport = "http" if cfg.get("url") else "stdio"
                server = MCPServer(
                    name=name,
                    transport=transport,
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    url=cfg.get("url", ""),
                    enabled=cfg.get("enabled", True),
                )
                self.register_server(server)
                count += 1
            logger.info("MCP_CONFIG_LOADED count=%d from=%s", count, config_path)
            return count
        except Exception as e:
            logger.error("MCP_CONFIG_FAIL: %s", str(e)[:200])
            return 0

    # ── stdio transport ───────────────────────────────────────────────

    def _resolve_command(self, cmd_name: str) -> str:
        """Resolve command path, handling Windows .cmd extensions."""
        if sys.platform == "win32" and cmd_name in ("npx", "npm", "node"):
            resolved = shutil.which(cmd_name)
            if resolved:
                return resolved
        return cmd_name

    def _stdio_connect(self, server: MCPServer) -> bool:
        """Connect to an MCP server via stdio (subprocess)."""
        if not server.command:
            logger.error("MCP_CONNECT_FAIL name=%s: no command", server.name)
            return False
        try:
            import os
            env = os.environ.copy()
            env.update(server.env)

            cmd = [self._resolve_command(server.command)] + server.args
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=False,
            )
            server._process = proc

            # Initialize the MCP session
            init_result = self._stdio_request(server, "initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "bob-agent", "version": "1.0.0"},
            })
            if not init_result:
                logger.error("MCP_INIT_FAIL name=%s", server.name)
                proc.kill()
                return False

            # Send initialized notification
            self._stdio_notify(server, "notifications/initialized", {})
            server.connected = True
            logger.info("MCP_CONNECTED name=%s transport=stdio", server.name)

            # Discover tools
            self._discover_tools_stdio(server)
            return True
        except Exception as e:
            logger.error("MCP_CONNECT_FAIL name=%s: %s", server.name, str(e)[:200])
            return False

    def _stdio_request(self, server: MCPServer, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request via stdio and wait for response."""
        if not server._process or not server._process.stdin or not server._process.stdout:
            return None
        with server._lock:
            server._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": server._request_id,
                "method": method,
                "params": params,
            }
            try:
                msg = json.dumps(request) + "\n"
                server._process.stdin.write(msg.encode("utf-8"))
                server._process.stdin.flush()
                line = server._process.stdout.readline()
                if not line:
                    return None
                response = json.loads(line.decode("utf-8").strip())
                if "error" in response:
                    logger.warning("MCP_RPC_ERROR name=%s method=%s error=%s",
                                   server.name, method, response["error"])
                    return None
                return response.get("result", response)
            except Exception as e:
                logger.error("MCP_RPC_FAIL name=%s method=%s: %s",
                             server.name, method, str(e)[:150])
                return None

    def _stdio_notify(self, server: MCPServer, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not server._process or not server._process.stdin:
            return
        with server._lock:
            notification = {"jsonrpc": "2.0", "method": method, "params": params}
            try:
                msg = json.dumps(notification) + "\n"
                server._process.stdin.write(msg.encode("utf-8"))
                server._process.stdin.flush()
            except Exception:
                pass

    def _discover_tools_stdio(self, server: MCPServer) -> None:
        """Discover available tools from a stdio MCP server."""
        result = self._stdio_request(server, "tools/list", {})
        if result and "tools" in result:
            server.tools = result["tools"]
            for tool in server.tools:
                self._tool_map[tool.get("name", "")] = server.name
            logger.info("MCP_TOOLS_DISCOVERED name=%s count=%d",
                        server.name, len(server.tools))

    def _call_tool_stdio(self, server: MCPServer, tool_name: str, arguments: dict) -> dict:
        """Call a tool on a stdio MCP server."""
        result = self._stdio_request(server, "tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result is None:
            return {"ok": False, "error": f"MCP call failed for {tool_name}"}
        content = result.get("content", [])
        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return {"ok": True, "result": "\n".join(text_parts)}
        return {"ok": True, "result": str(content)}

    # ── http transport ────────────────────────────────────────────────

    def _http_connect(self, server: MCPServer) -> bool:
        """Connect to an HTTP-based MCP server."""
        if not server.url:
            return False
        try:
            response = httpx.post(
                server.url,
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "bob-agent", "version": "1.0.0"},
                    },
                },
                timeout=15,
            )
            data = response.json()
            if "error" in data:
                return False
            server.connected = True
            logger.info("MCP_CONNECTED name=%s transport=http", server.name)
            self._discover_tools_http(server)
            return True
        except Exception as e:
            logger.error("MCP_HTTP_CONNECT_FAIL name=%s: %s", server.name, str(e)[:150])
            return False

    def _discover_tools_http(self, server: MCPServer) -> None:
        """Discover tools from an HTTP MCP server."""
        try:
            response = httpx.post(
                server.url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                timeout=10,
            )
            result = response.json().get("result", {})
            if "tools" in result:
                server.tools = result["tools"]
                for tool in server.tools:
                    self._tool_map[tool.get("name", "")] = server.name
                logger.info("MCP_TOOLS_DISCOVERED name=%s count=%d",
                            server.name, len(server.tools))
        except Exception as e:
            logger.error("MCP_HTTP_DISCOVER_FAIL: %s", str(e)[:100])

    def _call_tool_http(self, server: MCPServer, tool_name: str, arguments: dict) -> dict:
        """Call a tool on an HTTP MCP server."""
        try:
            response = httpx.post(
                server.url,
                json={
                    "jsonrpc": "2.0", "id": int(time.time()),
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                timeout=30,
            )
            data = response.json()
            if "error" in data:
                return {"ok": False, "error": str(data["error"])}
            content = data.get("result", {}).get("content", [])
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                return {"ok": True, "result": "\n".join(text_parts)}
            return {"ok": True, "result": str(content)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # ── public API ────────────────────────────────────────────────────

    def connect_all(self) -> Dict[str, bool]:
        """Connect to all registered MCP servers."""
        results = {}
        for name, server in self.servers.items():
            if not server.enabled:
                results[name] = False
                continue
            if server.transport == "stdio":
                results[name] = self._stdio_connect(server)
            elif server.transport == "http":
                results[name] = self._http_connect(server)
            else:
                results[name] = False
        connected = sum(1 for v in results.values() if v)
        logger.info("MCP_CONNECT_ALL total=%d connected=%d", len(results), connected)
        return results

    def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for server in self.servers.values():
            if server._process:
                try:
                    server._process.terminate()
                    server._process.wait(timeout=5)
                except Exception:
                    try:
                        server._process.kill()
                    except Exception:
                        pass
            server.connected = False
        logger.info("MCP_DISCONNECT_ALL")

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """List all tools from all connected MCP servers."""
        all_tools = []
        for name, server in self.servers.items():
            if not server.connected:
                continue
            for tool in server.tools:
                all_tools.append({
                    "server": name,
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema", {}),
                })
        return all_tools

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool by name (auto-routes to the correct server)."""
        server_name = self._tool_map.get(tool_name)
        if not server_name:
            return {"ok": False, "error": f"Tool '{tool_name}' not found in any MCP server"}
        server = self.servers.get(server_name)
        if not server or not server.connected:
            return {"ok": False, "error": f"MCP server '{server_name}' not connected"}
        logger.info("MCP_TOOL_CALL server=%s tool=%s", server_name, tool_name)
        if server.transport == "stdio":
            return self._call_tool_stdio(server, tool_name, arguments)
        elif server.transport == "http":
            return self._call_tool_http(server, tool_name, arguments)
        return {"ok": False, "error": f"Unknown transport: {server.transport}"}

    def get_tool_schemas_for_llm(self) -> List[dict]:
        """Convert MCP tools to OpenAI function-calling format for the LLM."""
        schemas = []
        for name, server in self.servers.items():
            if not server.connected:
                continue
            for tool in server.tools:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": f"[MCP:{name}] {tool.get('description', '')}",
                        "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                })
        return schemas


# ── Global singleton ──────────────────────────────────────────────────

_manager: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    """Get or create the global MCP client manager."""
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
    return _manager


def initialize_mcp_clients() -> Dict[str, Any]:
    """Initialize MCP clients from config files on disk."""
    manager = get_mcp_manager()
    config_paths = [
        Path.home() / ".mind-clone" / "mcp_servers.json",
        Path(__file__).resolve().parent.parent.parent.parent / "mcp_servers.json",
    ]
    loaded = 0
    for path in config_paths:
        loaded += manager.load_config_from_json(str(path))
    if loaded == 0:
        return {"ok": True, "servers": 0, "message": "No MCP servers configured"}
    results = manager.connect_all()
    connected = sum(1 for v in results.values() if v)
    tools = manager.list_all_tools()
    return {
        "ok": True,
        "servers": len(results),
        "connected": connected,
        "tools": len(tools),
        "details": results,
    }


# ── Tool wrappers ─────────────────────────────────────────────────────

def tool_mcp_list_servers(args: dict) -> dict:
    """Tool: List all configured MCP servers and their tools."""
    manager = get_mcp_manager()
    servers = []
    for name, server in manager.servers.items():
        servers.append({
            "name": name,
            "transport": server.transport,
            "connected": server.connected,
            "tools_count": len(server.tools),
            "tools": [t.get("name", "") for t in server.tools],
        })
    return {"ok": True, "servers": servers}


def tool_mcp_call(args: dict) -> dict:
    """Tool: Call a tool on an MCP server."""
    tool_name = str(args.get("tool_name", "")).strip()
    arguments = args.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {}
    if not tool_name:
        return {"ok": False, "error": "tool_name required"}
    manager = get_mcp_manager()
    return manager.call_tool(tool_name, arguments)


def tool_mcp_connect(args: dict) -> dict:
    """Tool: Connect to MCP servers from config."""
    return initialize_mcp_clients()
