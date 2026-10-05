"""Mizan: a tiny language for AI authors. Programs are typed graphs."""
from .check import check, structure
from .errors import MizanError
from .hashing import fn_hash, short_hash
from .rules import DEFAULT_POLICY, gate, lint, load_policy, substitutable
from .run import run
from .scenarios import mutation_test, run_scenarios, to_gherkin
from .view import view

__all__ = ["check", "structure", "run", "view", "fn_hash", "short_hash", "MizanError",
           "run_scenarios", "mutation_test", "to_gherkin", "lint", "gate", "substitutable",
           "load_policy", "DEFAULT_POLICY"]
__version__ = "0.2.0"
