"""
Mind Clone Agent - A sovereign AI agent platform.
"""

__version__ = "0.1.0"
__author__ = "Mind Clone Team"

from .config import settings
from .utils import truncate_text, utc_now_iso
from .database.session import init_db

__all__ = [
    "settings",
    "truncate_text",
    "utc_now_iso",
    "init_db",
]
