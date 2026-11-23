"""Memo Cup: a local-first persistent memory layer for AI applications."""

__version__ = "0.1.0"

from .client import MemoCupClient
from .store import MemoryStore

__all__ = ["MemoCupClient", "MemoryStore", "__version__"]
