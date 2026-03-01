#!/usr/bin/env python3
"""
Mind Clone Agent - Application Entry Point

This module serves as the main entry point for the Mind Clone Agent.
It handles CLI argument parsing, mode selection, and wires everything together.

Usage:
    python runner.py                    # Start web server (default)
    python runner.py --web              # Start web server explicitly
    python runner.py --telegram-poll    # Start Telegram polling mode
    python runner.py --run "task"       # Execute one-shot task
"""

# ============================================================================
# IMPORTS
# ============================================================================

import argparse
import asyncio
import logging
import sys
from typing import Optional

import uvicorn

# Agent core imports
from .database.session import init_db
from .agent.identity import load_identity
from .agent.llm import call_llm
from .api.factory import create_app

# Services
from .services.telegram import initialize_telegram, run_polling
from .services.task_engine import create_task, list_tasks
from .core.tools import (
    load_remote_node_registry,
    load_plugin_tools_registry,
    load_custom_tools_from_db,
)

# Configuration
from .config import (
    # Model
    KIMI_MODEL,
    KIMI_FALLBACK_MODEL,
    llm_failover_active,
    # Autonomy & Policy
    AUTONOMY_MODE,
    POLICY_PACK,
    # Command Queue
    COMMAND_QUEUE_MODE,
    COMMAND_QUEUE_MAX_SIZE,
    COMMAND_QUEUE_WORKER_COUNT,
    COMMAND_QUEUE_LANE_LIMITS,
    # Budget Governor
    BUDGET_GOVERNOR_ENABLED,
    BUDGET_GOVERNOR_MODE,
    BUDGET_MAX_SECONDS,
    BUDGET_MAX_TOOL_CALLS,
    BUDGET_MAX_LLM_CALLS,
    # Approval & Security
    APPROVAL_GATE_MODE,
    APPROVAL_TOKEN_TTL_MINUTES,
    active_tool_policy,
    active_tool_policy_profile,
    SECRET_GUARDRAIL_ENABLED,
    # Workspace & Diff
    WORKSPACE_DIFF_GATE_ENABLED,
    WORKSPACE_DIFF_GATE_MODE,
    WORKSPACE_DIFF_MAX_CHANGED_LINES,
    # Sandbox
    active_execution_sandbox_profile,
    EXECUTION_SANDBOX_REMOTE_ALLOWLIST,
    OS_SANDBOX_MODE,
    OS_SANDBOX_DOCKER_IMAGE,
    _normalize_os_sandbox_mode,
    # Desktop Control
    DESKTOP_CONTROL_ENABLED,
    DESKTOP_FAILSAFE_ENABLED,
    # Plugins
    PLUGIN_ENABLE_DYNAMIC_TOOLS,
    PLUGIN_TOOL_REGISTRY,
    PLUGIN_ENFORCE_TRUST,
    # Custom Tools
    CUSTOM_TOOL_ENABLED,
    CUSTOM_TOOL_REGISTRY,
    CUSTOM_TOOL_MAX_PER_USER,
    # Remote Nodes
    REMOTE_NODE_REGISTRY,
    # Task Graph
    TASK_GRAPH_BRANCHING_ENABLED,
    TASK_GRAPH_MAX_NODES,
    TASK_ARTIFACT_RETRIEVE_TOP_K,
    TASK_ARTIFACT_MAX_PER_USER,
    # Cron
    CRON_ENABLED,
    CRON_TICK_SECONDS,
    # Runtime Guards
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    TASK_GUARD_ORPHAN_LEASE_SECONDS,
    # Node Control Plane
    NODE_CONTROL_PLANE_ENABLED,
    NODE_HEARTBEAT_STALE_SECONDS,
    NODE_LEASE_TTL_SECONDS,
    # Checkpoints
    TASK_CHECKPOINT_SNAPSHOT_ENABLED,
    TASK_CHECKPOINT_MAX_PER_TASK,
    # Usage & Heartbeat
    USAGE_LEDGER_ENABLED,
    HEARTBEAT_AUTONOMY_ENABLED,
    HEARTBEAT_INTERVAL_SECONDS,
    # Task Role Loop
    TASK_ROLE_LOOP_ENABLED,
    TASK_ROLE_LOOP_MODE,
    # Eval Harness
    EVAL_HARNESS_ENABLED,
    RELEASE_GATE_MIN_PASS_RATE,
    RELEASE_GATE_REQUIRE_ZERO_FAILS,
    # Workflow
    WORKFLOW_V2_ENABLED,
    WORKFLOW_LOOP_MAX_ITERATIONS,
    # Canary Router
    CANARY_ROUTER_ENABLED,
    CANARY_PROFILE_NAME,
    CANARY_TRAFFIC_PERCENT,
    # Ops Auth
    OPS_AUTH_ENABLED,
    # Webhook
    WEBHOOK_BASE_URL,
)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("mind_clone.runner")


# ============================================================================
# CLI ARGUMENT PARSER
# ============================================================================


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="mind-clone-agent",
        description="Mind Clone Agent - An autonomous AI agent with reasoning, memory, and tool mastery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          Start web server (default mode)
  %(prog)s --web                    Start web server explicitly
  %(prog)s --telegram-poll          Start Telegram polling mode
  %(prog)s --run "hello world"      Execute one-shot task
  %(prog)s --host 127.0.0.1         Bind to specific host
  %(prog)s --port 8080              Use custom port
        """,
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--web",
        action="store_true",
        help="Start the web server (FastAPI + Uvicorn) [default]",
    )
    mode_group.add_argument(
        "--telegram-poll",
        action="store_true",
        help="Start Telegram bot in polling mode (no webhook required)",
    )
    mode_group.add_argument(
        "--run",
        metavar="TASK",
        type=str,
        help="Execute a one-shot task and exit",
    )

    # Server configuration
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (default: 1)",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress non-error output",
    )

    return parser


# ============================================================================
# STARTUP BANNER
# ============================================================================


def print_startup_banner() -> None:
    """Print the agent startup configuration banner."""
    policy_profile = active_tool_policy_profile()
    write_scope = "root-scoped"

    print("=" * 60)
    print("  MIND CLONE AGENT")

    fallback_display = KIMI_FALLBACK_MODEL if llm_failover_active() else "disabled"
    print(f"  Model: {KIMI_MODEL}")
    print(f"  Fallback: {fallback_display}")
    print(f"  Autonomy Mode: {AUTONOMY_MODE}")
    print(f"  Policy Pack: {POLICY_PACK}")
    print(f"  Command Queue: mode={COMMAND_QUEUE_MODE} max={COMMAND_QUEUE_MAX_SIZE}")
    print(f"  Queue Workers: {COMMAND_QUEUE_WORKER_COUNT} lanes={COMMAND_QUEUE_LANE_LIMITS}")
    print(
        f"  Budget Governor: enabled={BUDGET_GOVERNOR_ENABLED} mode={BUDGET_GOVERNOR_MODE} "
        f"max_sec={BUDGET_MAX_SECONDS} max_tools={BUDGET_MAX_TOOL_CALLS} max_llm={BUDGET_MAX_LLM_CALLS}"
    )
    print(f"  Approval Gate: mode={APPROVAL_GATE_MODE} ttl_min={APPROVAL_TOKEN_TTL_MINUTES}")
    print(f"  Tool Policy: {active_tool_policy_profile()} ({write_scope})")
    print(
        f"  Diff Gate: enabled={WORKSPACE_DIFF_GATE_ENABLED} mode={WORKSPACE_DIFF_GATE_MODE} "
        f"max_changed={WORKSPACE_DIFF_MAX_CHANGED_LINES}"
    )
    print(f"  Secret Guardrail: enabled={SECRET_GUARDRAIL_ENABLED}")
    print(
        f"  Sandbox Profile: {active_execution_sandbox_profile()} remote_allowlist={sorted(EXECUTION_SANDBOX_REMOTE_ALLOWLIST)[:6]}"
    )
    print(
        f"  OS Sandbox: mode={_normalize_os_sandbox_mode(OS_SANDBOX_MODE)} image={OS_SANDBOX_DOCKER_IMAGE}"
    )
    print(
        f"  Desktop Control: enabled={DESKTOP_CONTROL_ENABLED} failsafe={DESKTOP_FAILSAFE_ENABLED}"
    )
    print(
        f"  Plugins: enabled={PLUGIN_ENABLE_DYNAMIC_TOOLS} loaded={len(PLUGIN_TOOL_REGISTRY or [])} "
        f"enforce_trust={PLUGIN_ENFORCE_TRUST}"
    )
    print(
        f"  Custom Tools: enabled={CUSTOM_TOOL_ENABLED} loaded={len(CUSTOM_TOOL_REGISTRY or [])} max_per_user={CUSTOM_TOOL_MAX_PER_USER}"
    )
    print(f"  Remote Nodes: {len(REMOTE_NODE_REGISTRY or [])}")
    print(
        f"  Task Graph: branching={TASK_GRAPH_BRANCHING_ENABLED} max_nodes={TASK_GRAPH_MAX_NODES}"
    )
    print(
        f"  Task Memory: top_k={TASK_ARTIFACT_RETRIEVE_TOP_K} retain={TASK_ARTIFACT_MAX_PER_USER}"
    )
    print(f"  Cron: enabled={CRON_ENABLED} tick={CRON_TICK_SECONDS}s")
    print(
        f"  Runtime Guards: circuit={CIRCUIT_BREAKER_FAILURE_THRESHOLD}/{CIRCUIT_BREAKER_COOLDOWN_SECONDS}s "
        f"orphan_lease={TASK_GUARD_ORPHAN_LEASE_SECONDS}s"
    )
    print(
        f"  Node Control Plane: enabled={NODE_CONTROL_PLANE_ENABLED} "
        f"stale={NODE_HEARTBEAT_STALE_SECONDS}s lease_ttl={NODE_LEASE_TTL_SECONDS}s"
    )
    print(
        f"  Checkpoints: enabled={TASK_CHECKPOINT_SNAPSHOT_ENABLED} max_per_task={TASK_CHECKPOINT_MAX_PER_TASK}"
    )
    print(f"  Usage Ledger: enabled={USAGE_LEDGER_ENABLED}")
    print(
        f"  Heartbeat: autonomy={HEARTBEAT_AUTONOMY_ENABLED} interval={HEARTBEAT_INTERVAL_SECONDS}s"
    )
    print(f"  Task Role Loop: enabled={TASK_ROLE_LOOP_ENABLED} mode={TASK_ROLE_LOOP_MODE}")
    print(
        f"  Eval Harness: enabled={EVAL_HARNESS_ENABLED} "
        f"release_gate_min={RELEASE_GATE_MIN_PASS_RATE:.2f} zero_fails={RELEASE_GATE_REQUIRE_ZERO_FAILS}"
    )
    print(f"  Workflow V2: enabled={WORKFLOW_V2_ENABLED} loop_max={WORKFLOW_LOOP_MAX_ITERATIONS}")
    print(
        f"  Canary Router: enabled={CANARY_ROUTER_ENABLED} profile={CANARY_PROFILE_NAME} "
        f"traffic={CANARY_TRAFFIC_PERCENT}%"
    )
    print(f"  Ops Auth: enabled={OPS_AUTH_ENABLED}")
    print(f"  Webhook: {WEBHOOK_BASE_URL}/telegram/webhook")
    print("=" * 60)


def initialize_services() -> None:
    """Initialize all required services and registries."""
    log.info("Initializing database...")
    init_db()

    log.info("Loading remote node registry...")
    load_remote_node_registry()

    log.info("Loading plugin tools registry...")
    load_plugin_tools_registry()

    log.info("Loading custom tools from database...")
    load_custom_tools_from_db()

    log.info("Services initialized successfully")


# ============================================================================
# UVICORN SERVER STARTUP
# ============================================================================


def start_web_server(
    host: str = "0.0.0.0", port: int = 8000, reload: bool = False, workers: int = 1
) -> None:
    """
    Start the Uvicorn web server with FastAPI application.

    Args:
        host: Host address to bind to
        port: Port number to listen on
        reload: Enable auto-reload for development
        workers: Number of worker processes
    """
    # Create FastAPI app
    app = create_app()

    # Configure Uvicorn
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level="info",
        access_log=True,
    )

    server = uvicorn.Server(config)

    log.info(f"Starting web server on {host}:{port}")
    print(f"\n[OK] Server running at http://{host}:{port}")
    print(f"[OK] Health check: http://{host}:{port}/health")
    print(f"[OK] API docs: http://{host}:{port}/docs\n")

    try:
        server.run()
    except KeyboardInterrupt:
        log.info("Server shutdown requested")
        print("\n[OK] Goodbye!")


# ============================================================================
# TELEGRAM POLLING MODE
# ============================================================================


async def start_telegram_polling() -> None:
    """
    Start the Telegram bot in polling mode.

    This mode doesn't require a webhook URL and is useful for local development
    or environments where webhooks are not available.
    """
    log.info("Starting Telegram bot in polling mode...")
    try:
        await run_polling()
        print("\nTelegram bot started in polling mode")
        print("Press Ctrl+C to stop\n")
    except Exception as e:
        log.error(f"Telegram polling error: {e}")
        raise


def run_telegram_polling() -> None:
    """Run Telegram polling mode (sync wrapper for async function)."""
    try:
        asyncio.run(start_telegram_polling())
    except KeyboardInterrupt:
        print("\n👋 Telegram bot stopped")


# ============================================================================
# ONE-SHOT TASK EXECUTION MODE
# ============================================================================


async def execute_one_shot_task(task_description: str) -> None:
    """
    Execute a single task and exit.

    Args:
        task_description: Natural language description of the task to execute
    """
    log.info(f"Executing one-shot task: {task_description}")
    print(f"\n🎯 Task: {task_description}\n")

    from .database.session import SessionLocal
    from .services.task_engine import create_task, run_task
    db = SessionLocal()
    try:
        task = create_task(db, owner_id=1, title="CLI Task", description=task_description)
        result = run_task(db, task)

        print("\n" + "=" * 60)
        print("✅ Task completed successfully")
        print("=" * 60)
        print(f"\nResult:\n{result}")

    except Exception as e:
        log.error(f"Task execution failed: {e}")
        print(f"\nTask failed: {e}")
        sys.exit(1)
    finally:
        db.close()


def run_one_shot_task(task_description: str) -> None:
    """Run one-shot task mode (sync wrapper for async function)."""
    asyncio.run(execute_one_shot_task(task_description))


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def main(args: Optional[list[str]] = None) -> int:
    """
    Main entry point for the Mind Clone Agent.

    Args:
        args: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    # Configure logging based on verbosity
    if parsed_args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif parsed_args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Initialize services (database, registries, etc.)
    initialize_services()

    # Print startup banner
    if not parsed_args.quiet:
        print_startup_banner()

    # Determine execution mode
    try:
        if parsed_args.telegram_poll:
            # Telegram polling mode
            run_telegram_polling()

        elif parsed_args.run:
            # One-shot task execution mode
            run_one_shot_task(parsed_args.run)

        else:
            # Default: Web server mode (--web or no args)
            start_web_server(
                host=parsed_args.host,
                port=parsed_args.port,
                reload=parsed_args.reload,
                workers=parsed_args.workers,
            )

    except Exception as e:
        log.exception("Fatal error during execution")
        print(f"\n[ERROR] Fatal error: {e}")
        return 1

    return 0


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    sys.exit(main())
