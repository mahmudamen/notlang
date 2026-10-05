"""Reference solutions, built with a tiny helper. Used by the mock model and tests."""


class B:
    def __init__(self, label, params, returns, effects=("db.read",)):
        self.g = {"mizan": "0.1", "label": label, "params": params, "returns": returns,
                  "effects": list(effects), "nodes": {}}
        self.k = 0

    def n(self, op, *ins, **attrs):
        self.k += 1
        nid = f"n{self.k}"
        node = {"op": op, **attrs}
        if ins:
            node["in"] = list(ins)
        self.g["nodes"][nid] = node
        return nid

    def rows(self, table, key_node, key_field):
        return self.n("filter_eq", self.n("db.scan", table=table), key_node, field=key_field)

    def total(self, table, key_node, key_field, sum_field):
        return self.n("sum", self.n("pluck", self.rows(table, key_node, key_field), field=sum_field))

    def done(self, out, pre=(), post=()):
        self.g["out"] = out
        if pre:
            self.g["pre"] = list(pre)
        if post:
            self.g["post"] = list(post)
        return self.g


def _t01():
    b = B("partner_total", {"pid": "Int"}, "Money")
    pid = b.n("param", name="pid")
    tot = b.total("invoices", pid, "partner", "amount")
    pre = b.n("gt", pid, b.n("const", type="Int", value=0))
    post = b.n("ge", b.n("result"), b.n("const", type="Money", value="0"))
    return b.done(tot, [pre], [post])


def _t02():
    b = B("invoice_count", {"pid": "Int"}, "Int")
    pid = b.n("param", name="pid")
    return b.done(b.n("len", b.rows("invoices", pid, "partner")))


def _t03():
    b = B("entry_debit_total", {"eid": "Int"}, "Money")
    eid = b.n("param", name="eid")
    tot = b.total("journal_lines", eid, "entry", "debit")
    return b.done(tot, [b.n("gt", eid, b.n("const", type="Int", value=0))])


def _t04():
    b = B("entry_is_balanced", {"eid": "Int"}, "Bool")
    eid = b.n("param", name="eid")
    return b.done(b.n("eq", b.total("journal_lines", eid, "entry", "debit"),
                      b.total("journal_lines", eid, "entry", "credit")))


def _t05():
    b = B("net_balance", {"eid": "Int"}, "Money")
    eid = b.n("param", name="eid")
    return b.done(b.n("sub", b.total("journal_lines", eid, "entry", "debit"),
                      b.total("journal_lines", eid, "entry", "credit")))


def _t06():
    b = B("stock_on_hand", {"product": "Int"}, "Int")
    p = b.n("param", name="product")
    tot = b.total("stock_moves", p, "product", "qty")
    post = b.n("ge", b.n("result"), b.n("const", type="Int", value=0))
    return b.done(tot, post=[post])


def _t07():
    b = B("over_limit", {"pid": "Int", "limit": "Money"}, "Bool")
    pid, lim = b.n("param", name="pid"), b.n("param", name="limit")
    return b.done(b.n("gt", b.total("invoices", pid, "partner", "amount"), lim))


def _t08():
    b = B("discounted_total", {"pid": "Int"}, "Money")
    pid = b.n("param", name="pid")
    tot = b.total("invoices", pid, "partner", "amount")
    big = b.n("gt", tot, b.n("const", type="Money", value="1000"))
    less = b.n("sub", tot, b.n("const", type="Money", value="100"))
    return b.done(b.n("if", big, less, tot))


def _t09():
    b = B("audited_total", {"pid": "Int"}, "Money", effects=("db.read", "io.print"))
    pid = b.n("param", name="pid")
    return b.done(b.n("io.print", b.total("invoices", pid, "partner", "amount")))


def _t10():
    b = B("two_partner_total", {"a": "Int", "b": "Int"}, "Money")
    a, c = b.n("param", name="a"), b.n("param", name="b")
    return b.done(b.n("add", b.total("invoices", a, "partner", "amount"),
                      b.total("invoices", c, "partner", "amount")))


REFERENCE = {f"t{i:02d}": f() for i, f in enumerate(
    [_t01, _t02, _t03, _t04, _t05, _t06, _t07, _t08, _t09, _t10], start=1)}
