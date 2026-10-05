"""The operation table: single source of truth for the language.

Each op declares: arity, extra attributes, effects, a type rule, an evaluation rule and
the language version that introduced it. The checker, runner, viewer and the specs follow it.
"""
import operator as o
import re
from decimal import Decimal, InvalidOperation

from .errors import DomainRaise, MizanError, suggest

NUMERIC = ("Int", "Money")
SCALARS = ("Int", "Money", "Bool", "Str")
EFFECTS = ("db.read", "io.print")
ERROR_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")


def is_rows(t):
    return isinstance(t, str) and t.startswith("Rows<") and t.endswith(">")


def is_list(t):
    return isinstance(t, str) and t.startswith("List<") and t.endswith(">")


def inner(t):
    return t[t.index("<") + 1:-1]


def base(t, env):
    """Resolve a domain type (value object) to its scalar representation."""
    return env.types.get(t, t) if isinstance(t, str) else t


def known_type(t, env):
    return isinstance(t, str) and base(t, env) in SCALARS


def unknown_type(t, env):
    names = list(SCALARS) + sorted(env.types)
    return MizanError("type", "UNKNOWN_TYPE", f"unknown type {t!r}",
                      detail={"known": names, "did_you_mean": suggest(t, names)})


def parse_value(t, v, stage="type", types=None):
    """Turn a JSON literal into a runtime value. No implicit conversions."""
    t0 = t
    t = (types or {}).get(t, t)

    def bad(why):
        raise MizanError(stage, "BAD_LITERAL", f"{v!r} is not a valid {t0}: {why}",
                         detail={"type": t0, "value": v})

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
    if not known_type(t, env):
        raise unknown_type(t, env)
    parse_value(t, node["value"], types=env.types)
    return t


def t_param(node, ts, env):
    if node["name"] not in env.params:
        raise MizanError("type", "UNKNOWN_PARAM", f"no parameter named '{node['name']}'",
                         detail={"params": sorted(env.params),
                                 "did_you_mean": suggest(node["name"], env.params)})
    return env.params[node["name"]]


def t_result(node, ts, env):
    return env.returns


def t_arith(node, ts, env):
    a, b = ts
    if a == b and base(a, env) in NUMERIC:
        return a
    mismatch(node, ts, "needs two Int or two Money inputs of the same type")


def t_mul(node, ts, env):
    a, b = ts
    if a == "Int" and b == "Int":
        return "Int"
    if a == "Int" and base(b, env) in NUMERIC:
        return b
    if b == "Int" and base(a, env) in NUMERIC:
        return a
    mismatch(node, ts, "needs (Int, Int), or a raw Int with a numeric value")


def t_equal(node, ts, env):
    a, b = ts
    if a == b and base(a, env) in SCALARS:
        return "Bool"
    mismatch(node, ts, "needs two scalars of the same type")


def t_order(node, ts, env):
    a, b = ts
    if a == b and base(a, env) in NUMERIC:
        return "Bool"
    mismatch(node, ts, "needs two numeric inputs of the same type")


def t_logic(node, ts, env):
    if all(t == "Bool" for t in ts):
        return "Bool"
    mismatch(node, ts, "needs Bool inputs")


def t_if(node, ts, env):
    c, a, b = ts
    if c == "Bool" and a == b and base(a, env) in SCALARS:
        return a
    mismatch(node, ts, "needs (Bool, T, T) with T a scalar or domain type")


def t_scan(node, ts, env):
    table = node["table"]
    if not isinstance(table, str) or table not in env.schema:
        raise MizanError("type", "UNKNOWN_TABLE", f"no table named {table!r}",
                         detail={"tables": sorted(env.schema),
                                 "did_you_mean": suggest(table, env.schema)})
    if env.context is not None and table not in env.contexts.get(env.context, []):
        owners = sorted(c for c, tables in env.contexts.items() if table in tables)
        raise MizanError("type", "CONTEXT_VIOLATION",
                         f"context '{env.context}' may not read table '{table}'",
                         detail={"context": env.context, "table": table, "owned_by": owners})
    return f"Rows<{table}>"


def _field_type(env, rows_t, field):
    table = inner(rows_t)
    if field not in env.schema[table]:
        raise MizanError("type", "UNKNOWN_FIELD", f"table '{table}' has no field {field!r}",
                         detail={"fields": sorted(env.schema[table]),
                                 "did_you_mean": suggest(field, env.schema[table])})
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
    if is_list(t) and base(inner(t), env) in NUMERIC:
        return inner(t)
    mismatch(node, ts, "needs a List of numeric values")


def t_len(node, ts, env):
    (t,) = ts
    if is_list(t) or is_rows(t):
        return "Int"
    mismatch(node, ts, "needs a List or Rows")


def t_print(node, ts, env):
    (t,) = ts
    if base(t, env) in SCALARS:
        return t
    mismatch(node, ts, "needs a scalar or domain value")


def t_wrap(node, ts, env):
    (x,) = ts
    target = node["as"]
    if not isinstance(target, str) or target not in env.types:
        raise MizanError("type", "UNKNOWN_TYPE", f"{target!r} is not a domain type",
                         detail={"domain_types": sorted(env.types),
                                 "did_you_mean": suggest(target, env.types)})
    if x != env.types[target]:
        mismatch(node, ts, f"wraps a raw {env.types[target]} into {target}")
    return target


def t_unwrap(node, ts, env):
    (x,) = ts
    if x in env.types:
        return env.types[x]
    mismatch(node, ts, "needs a domain value")


def _error_name(name, where):
    if not isinstance(name, str) or not ERROR_NAME.fullmatch(name):
        raise MizanError("type", "BAD_ERROR_NAME", f"{where} must be a PascalCase name, got {name!r}")


def t_fail(node, ts, env):
    _error_name(node["error"], "error")
    if not isinstance(node["message"], str):
        raise MizanError("type", "BAD_MESSAGE", "fail needs a string message")
    t = node["type"]
    if not known_type(t, env):
        raise unknown_type(t, env)
    return t


def t_try(node, ts, env):
    _error_name(node["catch"], "catch")
    a, b = ts
    if a == b and base(a, env) in SCALARS:
        return a
    mismatch(node, ts, "needs (body, fallback) of the same scalar or domain type")


# ---- eval rules: (node, get, ctx, type) -> value ------------------------------
# get(i) evaluates the i-th input on demand, so `if`/`and`/`or`/`try` are lazy.

def _bin(f):
    return lambda node, get, ctx, ty: f(get(0), get(1))


def e_const(node, get, ctx, ty):
    return parse_value(ty, node["value"], types=ctx.domain_types)


def e_sum(node, get, ctx, ty):
    return sum(get(0), Decimal(0) if ctx.domain_types.get(ty, ty) == "Money" else 0)


def e_print(node, get, ctx, ty):
    v = get(0)
    ctx.printed.append(str(v))
    return v


def e_fail(node, get, ctx, ty):
    raise DomainRaise(node["error"], node["message"])


def e_try(node, get, ctx, ty):
    try:
        return get(0)
    except DomainRaise as e:
        if e.name != node["catch"]:
            raise
        return get(1)


OPS = {}


def _op(name, arity, attrs, check, ev, effects=(), since="0.1"):
    OPS[name] = {"arity": arity, "attrs": tuple(attrs), "check": check, "eval": ev,
                 "effects": tuple(effects), "since": since}


_op("const", 0, ["type", "value"], t_const, e_const)
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
# ---- v0.2 ----
_op("wrap", 1, ["as"], t_wrap, lambda n, g, c, ty: g(0), since="0.2")
_op("unwrap", 1, [], t_unwrap, lambda n, g, c, ty: g(0), since="0.2")
_op("fail", 0, ["error", "type", "message"], t_fail, e_fail, since="0.2")
_op("try", 2, ["catch"], t_try, e_try, since="0.2")
