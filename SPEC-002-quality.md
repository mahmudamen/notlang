# SPEC-002: Mizan v0.2 (the quality charter)

**Status:** Draft, matches the reference interpreter in `mizan/`. Builds on [SPEC-001](SPEC-001.md).
A program that says `"mizan": "0.1"` keeps working unchanged. Programs that use anything below must say `"mizan": "0.2"` (otherwise `NEEDS_V02`).

## 1. Why this exists

If humans do not read the code, a style guide is useless: nobody is there to follow it. So every practice a team cares about has to become a rule the toolchain **checks**, and nothing ships until the checks pass. This document maps each practice to a feature.

| Practice | Rule in Mizan | Enforced by |
|---|---|---|
| **Clean Code** | No magic values (`why` notes), no dead nodes, no duplicate subgraphs (DRY), shallow and small functions, snake_case names, compiler hints and "did you mean" | `mizan lint`, `mizan gate`, the checker |
| **TDD** | Scenarios live inside the program; mutation testing proves the tests can fail; every contract must be exercised | `mizan test`, `mizan mutate`, `mizan gate` |
| **BDD** | Scenarios are Given / When / Then; a generator turns them into Gherkin a human can review instead of the code | `mizan spec` |
| **DDD** | Value objects (distinct domain types), bounded contexts, a glossary (ubiquitous language) | the type checker, `mizan lint` |
| **SOLID-S** | Size limits, and no mixing of concerns (a forbidden-effect-mix rule, in the spirit of CQS) | `mizan lint` |
| **SOLID-O** | Functions are immutable and content-addressed: new behaviour is a new hash, never an edit | hashing (SPEC-001 section 8) |
| **SOLID-L** | A replacement must not demand more, promise less, use more effects or raise new errors | `mizan subst` |
| **SOLID-I** | No unused parameters, at most 3 parameters by default | `mizan lint` |
| **SOLID-D** | Functions depend on declared effects that the host grants, not on hard-wired I/O | effect grants (SPEC-001 section 6) |
| **Error handling** | Errors are declared, checked and catchable. No hidden exceptions | `raises`, `fail`, `try` |

## 2. Language additions

New top-level keys (all optional): `raises` (list of PascalCase error names), `context` (a bounded context name), `scenarios` (section 6).
New node key: `why` (a string that explains intent; ignored by hashing and by evaluation).

New operations:

| Op | Inputs | Attributes | Type rule |
|---|---|---|---|
| `wrap` | 1 | `as` | a raw scalar becomes the domain type `as` (the input must be exactly its base type) |
| `unwrap` | 1 | none | a domain value becomes its raw base scalar |
| `fail` | none | `error`, `type`, `message` | raises the declared domain error `error`. Has the type `type` so it can sit in a branch |
| `try` | 2: body, fallback | `catch` | `(T, T)` gives `T`. If the body raises `catch`, the fallback is evaluated instead. Lazy |

## 3. Exceptions

An exception is a **named, declared, checked** thing, never a surprise.

- `fail` raises a domain error. Error names are PascalCase, so they cannot collide with the interpreter's own codes (UPPER_SNAKE).
- The function's `raises` list must **exactly** equal the errors that can escape it, computed statically: a `fail` adds its error, a `try` removes the error it catches. An undeclared error is `RAISES_UNDECLARED`. A declared error that nothing raises is `RAISES_UNUSED`.
- A `try` whose body cannot raise its `catch` error is dead code and does not compile (`CATCH_UNREACHABLE`).
- `if` is lazy, so `if(enough, left, fail ...)` only raises when the failing branch is chosen. The static analysis is conservative and counts both branches.
- At run time an uncaught `fail` stops the run with `{"stage": "domain", "code": "<ErrorName>", "node": "<fail node>", ...}`.
- Callers can tell the three kinds of failure apart: `PRE_FAILED` means the caller is wrong, `POST_FAILED` means the body is wrong, and a domain error means the world said no.

Compiler help: every error may carry a `hint` (a one-line fix), and unknown names carry `detail.did_you_mean`.

```json
{"stage": "type", "code": "UNKNOWN_FIELD", "message": "table 'invoices' has no field 'amout'",
 "node": "amts", "detail": {"fields": ["amount", "id", "partner"], "did_you_mean": ["amount"]},
 "hint": "Use a field of that table."}
```

## 4. Domain model (DDD)

The domain model is the `domain` object in the database file:

```json
{"domain": {
   "types":    {"ProductId": "Int", "Qty": "Int", "Amount": "Money"},
   "contexts": {"inventory": ["stock_moves"], "accounting": ["invoices", "journal_lines"]},
   "glossary": {"Qty": "Signed number of units; a negative move takes stock out."}}}
```

- **Value objects.** A domain type (PascalCase, not a scalar name) is a distinct type with a scalar representation. `ProductId` and `PartnerId` are both `Int` underneath and can never be mixed, and a raw `Int` is not a `Qty`. Use `wrap` and `unwrap` to cross the boundary on purpose. Table fields, params, returns and constants may all use domain types. Arithmetic and comparison need the same domain type on both sides. Multiplying by a raw `Int` keeps the domain type.
- **Bounded contexts.** If a function declares `context`, it may only `db.scan` the tables its context owns (`CONTEXT_VIOLATION`). An unknown context is `UNKNOWN_CONTEXT`.
- **Ubiquitous language.** Every domain type a function uses must have a glossary entry (lint rule `require_glossary`).

## 5. Contracts as design

`pre` blames the caller, `post` blames the body (SPEC-001 section 7). Policy can require every function with parameters to have at least one contract (`require_contract`).

## 6. Scenarios (TDD + BDD)

```json
"scenarios": [
  {"title": "Refuse to over-reserve",
   "given": {"stock_moves": []},
   "when":  {"product": 1, "wanted": 8},
   "then":  {"error": "OutOfStock"}}
]
```

- `title` (required), `when` (arguments, required), `then` (required: exactly one of `result` or `error`, plus an optional `prints` list), `given` (optional: replaces whole tables for this scenario, otherwise the shared test data is used).
- A scenario runs with exactly the effects the function declares. `then.error` matches either a domain error name or a contract code such as `PRE_FAILED`.
- `mizan test` prints a red/green report. `mizan spec` renders the scenarios and contracts as Gherkin (Feature, Rule, Scenario, Given, When, Then). This is what humans review: the behaviour, not the graph.
- Scenarios are not part of a function's identity (hash).

### Mutation testing

`mizan mutate` makes small deliberate bugs ("mutants") in every **reachable** node and re-runs the scenarios. A mutant that no scenario notices is a **survivor**, which means a scenario is missing.

| Mutation | Example |
|---|---|
| Swap a comparison, arithmetic or logic op | `ge` becomes `gt`, `add` becomes `sub`, `and` becomes `or` |
| Swap the branches of an `if` | |
| Change a constant | Int `n` becomes `n+1`, Money `m` becomes `m+1`, Bool is flipped |

Mutants that no longer compile, or that hash the same as the original, are discarded. The score is killed / total.

### Contract coverage

A `pre` is **covered** if some scenario triggers it (`then: {"error": "PRE_FAILED"}`) or some mutant trips it. A `post` is covered if some mutant makes it fail, because a correct program never violates its own `post`, so the useful question is whether the `post` ever **catches a bug**. An uncovered contract is a contract nobody has proven useful.

## 7. The policy (our rules)

The rules live in `mizan.rules.json` (default: the file in the current directory, or `--policy FILE`). Missing keys fall back to these defaults.

| Key | Default | Principle |
|---|---|---|
| `min_scenarios` | 3 | BDD |
| `mutation_score_min` | 0.8 | TDD |
| `require_contract_coverage` | true | TDD |
| `require_contract` | true | Design by Contract |
| `max_nodes` | 30 | SOLID-S |
| `max_depth` | 8 | Clean Code |
| `max_params` | 3 | Clean Code, SOLID-I |
| `no_dead_nodes` | true | Clean Code |
| `no_duplicate_subgraphs` (`min_duplicate_size` 3) | true | Clean Code (DRY) |
| `no_unused_params` | true | SOLID-I |
| `magic_consts_need_why` (0, 1 and Bool are exempt) | true | Clean Code |
| `snake_case_names`, `require_label` | true | Clean Code |
| `require_context` (when the domain defines contexts) | true | DDD |
| `require_glossary` | true | DDD |
| `forbidden_effect_mixes` | `[["db.read","io.print"]]` | SOLID-S |

### The gate

`mizan gate FILE --db DB` runs, in order: **compile**, **tests** (all green, at least `min_scenarios`), **mutation** (score at least `mutation_score_min`), **coverage**, **lint**. The exit code is 0 only if everything passes. `--json` gives a machine-readable report that can be fed back to the author in a repair loop.

## 8. Liskov check

`mizan subst ORIGINAL REPLACEMENT` answers whether the replacement can stand in for the original. It must have the same signature, use no extra effects, raise no new errors, require **no more** (every precondition of the replacement is one the original already had) and promise **no less** (every postcondition of the original is still there). Contracts are compared by structural hash.

This is a **sufficient** check, not a complete one: it can say no to a replacement that is actually fine (for example, a precondition that is logically weaker but written differently). It will never say yes to one that breaks these rules.

## 9. Honest limitations

- Mutation testing has **equivalent mutants** (a change that cannot alter behaviour), which survive no matter what. The default threshold is 0.8, not 1.0, for that reason.
- The scenarios are written by the same AI that wrote the code, so they can share its misunderstanding. That is why `mizan spec` exists: a human reviews the Gherkin.
- Every threshold in the policy is a team choice, not a truth.
- Duplicate detection is structural (the same subgraph), not semantic.
- The viewer still inlines shared nodes, so large bodies read poorly.
- Contracts are still checked at run time only.
