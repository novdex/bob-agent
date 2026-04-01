"""Service Startup Registry — explicit initialization order.

Defines a deterministic startup sequence for all core services so that
import-order bugs are eliminated.  Each service is initialized exactly
once via ``init_service()``, and the global ``_initialized`` set tracks
what has already been brought up.

Usage::

    from mind_clone.core.startup import init_service, boot_all, is_initialized

    # Boot a single service
    init_service("database", my_db_init_func)

    # Boot everything in order (called from main entrypoint)
    boot_all(service_factories)
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("mind_clone.startup")

# Canonical startup order.  Services listed first are initialized first.
STARTUP_ORDER: List[str] = [
    "database",
    "config",
    "identity",
    "tools",
    "memory",
    "telegram",
    "cron",
    "health",
]

_initialized: set[str] = set()
_init_times: Dict[str, float] = {}


def init_service(name: str, init_func: Callable[[], None]) -> bool:
    """Initialize a service by name.  Tracks what has been initialized.

    Args:
        name: Logical service name (should match a value in ``STARTUP_ORDER``).
        init_func: Zero-argument callable that performs initialization.
                   Must raise on failure.

    Returns:
        ``True`` if the service initialized (or was already initialized),
        ``False`` on error.
    """
    if name in _initialized:
        logger.debug("SERVICE_ALREADY_INIT name=%s", name)
        return True
    t0 = time.monotonic()
    try:
        init_func()
        elapsed = time.monotonic() - t0
        _initialized.add(name)
        _init_times[name] = elapsed
        logger.info("SERVICE_INIT_OK name=%s elapsed=%.2fs", name, elapsed)
        return True
    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.error(
            "SERVICE_INIT_FAIL name=%s elapsed=%.2fs: %s",
            name, elapsed, str(e)[:200],
        )
        return False


def boot_all(
    service_factories: Dict[str, Callable[[], None]],
    *,
    stop_on_failure: bool = False,
) -> List[str]:
    """Boot every service in ``STARTUP_ORDER`` using the supplied factories.

    Args:
        service_factories: Mapping of service name -> init callable.
        stop_on_failure: If ``True``, abort on the first failure.

    Returns:
        List of service names that failed to initialize (empty on full success).
    """
    failed: List[str] = []
    for name in STARTUP_ORDER:
        factory = service_factories.get(name)
        if factory is None:
            logger.debug("SERVICE_SKIP name=%s (no factory registered)", name)
            continue
        ok = init_service(name, factory)
        if not ok:
            failed.append(name)
            if stop_on_failure:
                logger.error("BOOT_ABORT — stopping after %s failure", name)
                break
    if failed:
        logger.warning("BOOT_DONE failures=%s", failed)
    else:
        logger.info("BOOT_DONE all_ok services=%s", list(_initialized))
    return failed


def get_initialized() -> List[str]:
    """Return sorted list of currently initialized service names."""
    return sorted(_initialized)


def is_initialized(name: str) -> bool:
    """Check whether a service has been initialized."""
    return name in _initialized


def get_init_times() -> Dict[str, float]:
    """Return a copy of initialization times (seconds) per service."""
    return dict(_init_times)


def reset() -> None:
    """Reset all state (for testing only)."""
    _initialized.clear()
    _init_times.clear()
