"""Mizan: a tiny language for AI authors. Programs are typed graphs."""
from .check import check, structure
from .errors import MizanError
from .hashing import fn_hash, short_hash
from .run import run
from .view import view

__all__ = ["check", "structure", "run", "view", "fn_hash", "short_hash", "MizanError"]
__version__ = "0.1.0"
