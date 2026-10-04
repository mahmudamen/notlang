"""The operation table: single source of truth for Mizan v0.1.

Each op declares: arity, extra attributes, effects, a type rule and an
evaluation rule. The checker, the runner, the viewer and SPEC-001 all
follow this table.
"""
import operator as o
from decimal import Decimal, InvalidOperation

from .errors import MizanError

NUMERIC = ("Int", "Money")
SCALARS = ("Int", "Money", "Bool", "Str")
EFFECTS = ("db.read", "io.print")


def is_scalar_type(t):
    return t in SCALARS


def is_rows(t):
    return isinstance(t, str) and t.startswith("Rows<") and t.endswith(">")


def is_list(t):
    return isinstance(t, str) and t.startswith("List<") and t.endswith(">")


def inner(t):
    return t[t.index("<") + 1:-1]


def parse_value(t, v, stage="type"):
    """Turn a JSON literal into a runtime value. No implicit conversions."""
    def bad(why):
        raise MizanError(stage, "BAD_LITERAL", f"{v!r} is not a valid {t}: {why}",
                         detail={"type": t, "value": v})

    if t == "Int":
        if isinstance(v, bool) or not isinstance(v, int):
            bad("expected a JSON integer")
        return v
    if t == "Money":
        if isinstance(v, bool) or not isinstance(v, (int, str)):
            bad("expected a string or integer (floats are banned for money)")
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            bad("not a decimal number")
        if not d.is_finite():
            bad("must be finite")
        return d
    if t == "Bool":
        if not isinstance(v, bool):
            bad("expected true or false")
        return v
    if t == "Str":
        if not isinstance(v, str):
            bad("expected a string")
        return v
    bad("unknown type")


def mismatch(node, ts, hint):
    raise MizanError(
        "type", "TYPE_MISMATCH",
        f"op '{node['op']}' {hint}, got {', '.join(ts) if ts else 'no inputs'}",
        detail={"op": node["op"], "input_types": list(ts)})


# ---- type rules: (node, input_types, env) -> type ---------------------------

def t_const(node, ts, env):
    t = node["type"]
    if not is_scalar_type(t):
        raise MizanError("type", "BAD_LITERAL", f"const type must be one of {list(SCALARS)}",
                         detail={"type": t})
    parse_value(t, node["value"])
    return t


def t_param(node, ts, env):
    if node["name"] not in env.params:
        raise MizanError("type", "UNKNOWN_PARAM", f"no parameter named '{node['name']}'",
                         detail={"params": sorted(env.params)})
    return env.params[node["name"]]


def t_result(node, ts, env):
    return env.returns


def t_arith(node, ts, env):
    a, b = ts
    if a == b and a in NUMERIC:
        return a
    mismatch(node, ts, "needs two Int or two Money inputs")


def t_mul(node, ts, env):
    a, b = ts
    if a == "Int" and b == "Int":
        return "Int"
    if {a, b} == {"Int", "Money"}:
        return "Money"
    mismatch(node, ts, "needs (Int, Int), (Int, Money) or (Money, Int)")


def t_equal(node, ts, env):
    a, b = ts
    if a == b and a in SCALARS:
        return "Bool"
    mismatch(node, ts, "needs two scalars of the same type")


def t_order(node, ts, env):
    a, b = ts
    if a == b and a in NUMERIC:
        return "Bool"
    mismatch(node, ts, "needs two Int or two Money inputs")


def t_logic(node, ts, env):
    if all(t == "Bool" for t in ts):
        return "Bool"
    mismatch(node, ts, "needs Bool inputs")


def t_if(node, ts, env):
    c, a, b = ts
    if c == "Bool" and a == b and a in SCALARS:
        return a
    mismatch(node, ts, "needs (Bool, T, T) with T scalar")


def t_scan(node, ts, env):
    table = node["table"]
    if table not in env.schema:
        raise MizanError("type", "UNKNOWN_TABLE", f"no table named '{table}'",
                         detail={"tables": sorted(env.schema)})
    return f"Rows<{table}>"


def _field_type(env, rows_t, field):
    table = inner(rows_t)
    if field not in env.schema[table]:
        raise MizanError("type", "UNKNOWN_FIELD", f"table '{table}' has no field '{field}'",
                         detail={"fields": sorted(env.schema[table])})
    return env.schema[table][field]


def t_filter_eq(node, ts, env):
    rows, v = ts
    if not is_rows(rows):
        mismatch(node, ts, "needs (Rows, value)")
    ft = _field_type(env, rows, node["field"])
    if ft != v:
        mismatch(node, ts, f"needs a value of type {ft}")
    return rows


def t_pluck(node, ts, env):
    (rows,) = ts
    if not is_rows(rows):
        mismatch(node, ts, "needs Rows")
    return f"List<{_field_type(env, rows, node['field'])}>"


def t_sum(node, ts, env):
    (t,) = ts
    if is_list(t) and inner(t) in NUMERIC:
        return inner(t)
    mismatch(node, ts, "needs List<Int> or List<Money>")


def t_len(node, ts, env):
    (t,) = ts
    if is_list(t) or is_rows(t):
        return "Int"
    mismatch(node, ts, "needs a List or Rows")


def t_print(node, ts, env):
    (t,) = ts
    if t in SCALARS:
        return t
    mismatch(node, ts, "needs a scalar")


# ---- eval rules: (node, get, ctx, type) -> value ------------------------------
# get(i) evaluates the i-th input on demand, so `if`/`and`/`or` are lazy.

def _bin(f):
    return lambda node, get, ctx, ty: f(get(0), get(1))


def e_sum(node, get, ctx, ty):
    return sum(get(0), Decimal(0) if ty == "Money" else 0)


def e_print(node, get, ctx, ty):
    v = get(0)
    ctx.printed.append(str(v))
    return v


OPS = {}


def _op(name, arity, attrs, check, ev, effects=()):
    OPS[name] = {"arity": arity, "attrs": tuple(attrs), "check": check,
                 "eval": ev, "effects": tuple(effects)}


_op("const", 0, ["type", "value"], t_const, lambda n, g, c, ty: parse_value(ty, n["value"]))
_op("param", 0, ["name"], t_param, lambda n, g, c, ty: c.args[n["name"]])
_op("result", 0, [], t_result, lambda n, g, c, ty: c.result)
_op("add", 2, [], t_arith, _bin(o.add))
_op("sub", 2, [], t_arith, _bin(o.sub))
_op("mul", 2, [], t_mul, _bin(o.mul))
_op("eq", 2, [], t_equal, _bin(o.eq))
_op("ne", 2, [], t_equal, _bin(o.ne))
_op("gt", 2, [], t_order, _bin(o.gt))
_op("ge", 2, [], t_order, _bin(o.ge))
_op("lt", 2, [], t_order, _bin(o.lt))
_op("le", 2, [], t_order, _bin(o.le))
_op("and", 2, [], t_logic, lambda n, g, c, ty: g(0) and g(1))
_op("or", 2, [], t_logic, lambda n, g, c, ty: g(0) or g(1))
_op("not", 1, [], t_logic, lambda n, g, c, ty: not g(0))
_op("if", 3, [], t_if, lambda n, g, c, ty: g(1) if g(0) else g(2))
_op("db.scan", 0, ["table"], t_scan, lambda n, g, c, ty: c.tables[n["table"]], effects=["db.read"])
_op("filter_eq", 2, ["field"], t_filter_eq,
    lambda n, g, c, ty: [r for r in g(0) if r[n["field"]] == g(1)])
_op("pluck", 1, ["field"], t_pluck, lambda n, g, c, ty: [r[n["field"]] for r in g(0)])
_op("sum", 1, [], t_sum, e_sum)
_op("len", 1, [], t_len, lambda n, g, c, ty: len(g(0)))
_op("io.print", 1, [], t_print, e_print, effects=["io.print"])
