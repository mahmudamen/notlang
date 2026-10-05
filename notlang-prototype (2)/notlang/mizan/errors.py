"""Structured errors: the interpreter talks to the AI in data, not prose."""
import difflib
from decimal import Decimal

# One-line fix advice, attached to errors so an AI (or a tired human) can repair faster.
HINTS = {
    "TYPE_MISMATCH": "No implicit conversions. Fix a const's type, or use wrap/unwrap for domain types.",
    "UNKNOWN_OP": "Use one of the ops listed in detail.known.",
    "UNKNOWN_TYPE": "Use a scalar type or a domain type from the domain model.",
    "UNKNOWN_TABLE": "Use a table from the schema.",
    "UNKNOWN_FIELD": "Use a field of that table.",
    "UNKNOWN_PARAM": "Use a name from 'params'.",
    "UNKNOWN_CONTEXT": "Use a bounded context from the domain model.",
    "EFFECT_UNDECLARED": "Add the missing effect to 'effects'.",
    "EFFECT_UNUSED": "Remove the unused effect from 'effects' (least privilege).",
    "EFFECT_DENIED": "The host must grant the effect, or the function must not use it.",
    "RAISES_UNDECLARED": "Add the error to 'raises', or catch it with a 'try' node.",
    "RAISES_UNUSED": "Remove the name from 'raises': nothing can raise it.",
    "CATCH_UNREACHABLE": "Remove the 'try': its body cannot raise that error.",
    "CONTEXT_VIOLATION": "Read only tables owned by this bounded context, or change 'context'.",
    "PRE_FAILED": "The caller broke the contract: fix the arguments.",
    "POST_FAILED": "The body broke its promise: fix the body, or the contract if it is wrong.",
    "NEEDS_V02": "Set \"mizan\": \"0.2\" to use this feature.",
    "CYCLE": "A graph must be acyclic: remove one edge of the cycle.",
}


def suggest(word, options):
    """'Did you mean ...?' candidates."""
    return difflib.get_close_matches(str(word), sorted(str(o) for o in options), n=3, cutoff=0.5)


def jsonable(x):
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(jsonable(v) for v in x)
    return x


class DomainRaise(Exception):
    """A declared domain error raised by a `fail` node. Internal: becomes a MizanError at the top."""

    def __init__(self, name, message, node=None):
        super().__init__(f"{name}: {message}")
        self.name, self.message, self.node = name, message, node


class MizanError(Exception):
    """stage: shape | type | effect | args | contract | domain | runtime"""

    def __init__(self, stage, code, message, node=None, detail=None):
        super().__init__(f"[{stage}/{code}] {message}")
        self.stage = stage
        self.code = code
        self.message = message
        self.node = node
        self.detail = detail or {}

    def to_dict(self):
        d = {"stage": self.stage, "code": self.code, "message": self.message,
             "node": self.node, "detail": self.detail}
        if self.code in HINTS:
            d["hint"] = HINTS[self.code]
        return jsonable(d)
