"""Structured errors: the interpreter talks to the AI in data, not prose."""
from decimal import Decimal


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


class MizanError(Exception):
    """stage: shape | type | effect | args | contract | runtime"""

    def __init__(self, stage, code, message, node=None, detail=None):
        super().__init__(f"[{stage}/{code}] {message}")
        self.stage = stage
        self.code = code
        self.message = message
        self.node = node
        self.detail = detail or {}

    def to_dict(self):
        return jsonable({
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "node": self.node,
            "detail": self.detail,
        })
