# Mizan: A Programming Language Designed for AI, Not for Humans

**Paper 001 — Concept and Design Draft**
**Author:** Mahmoud Mohamed Amin, XamlTech
**Status:** Draft v0.1 (idea stage, no implementation yet)
**Working name:** Mizan (Arabic for "balance / scale"). The name is a placeholder and can change.

---

## Abstract

Every mainstream programming language was designed for humans: for human eyes, human memory, and human typing speed. As AI systems start to write most of the code, these design choices become costs instead of benefits. Flexible syntax, undefined behavior, and many ways to do the same thing all increase the chance that an AI produces code that looks right but is wrong.

This paper proposes **Mizan**, a language designed for AI as the primary author. Programs are **typed graphs**, not text files. Side effects are **declared**, every function carries a **machine-checkable contract**, and execution is **deterministic**. A natural-language prompt is translated by the AI into a Mizan graph, an interpreter validates and verifies the graph, and then runs it in a sandbox. Humans do not read or write the code. They review the **intent** (the spec and the tests) and use a read-only **viewer** to audit when needed.

This is a concept paper. It states the problem, the design principles, the execution model, and a prototype roadmap. It does not claim results.

---

## 1. Motivation

### 1.1 The assumption behind today's languages

Languages like Python, JavaScript, C++, and Java share one assumption: a human will write the code and a human will read it later. That assumption shaped everything:

- **Readable syntax** (keywords, indentation, naming).
- **Flexibility** (multiple ways to loop, many ways to build a string).
- **Implicit behavior** (type coercion, default values, hidden side effects).
- **Programmer control** (manual memory, raw pointers, direct system access).

### 1.2 Why these choices hurt AI authors

| Human-friendly feature | Cost when AI writes the code |
|---|---|
| Many equivalent ways to do one thing | More ways to guess wrong, and inconsistent output |
| Free-form syntax | Syntax errors are possible, and tokens are spent on formatting |
| Implicit conversions and defaults | Bugs that are valid code and silently wrong |
| Undefined behavior (C/C++) | Code compiles and misbehaves with no signal |
| Hidden side effects | The system cannot know what a program touches before running it |
| Verbose boilerplate | More tokens means more cost, more latency, more error surface |

### 1.3 The goal

Design a language where the **cheapest thing for an AI to generate is also the correct thing**, and where mistakes are caught by the machine before the program runs.

---

## 2. Design Goals

1. **Unambiguous.** One canonical way to express each idea.
2. **Invalid states are unrepresentable.** The AI can only emit well-formed programs.
3. **Deterministic.** The same input always gives the same output.
4. **Effects are visible.** The interpreter knows what a program can touch before it runs.
5. **Self-verifying.** Intent is attached to code as checkable contracts.
6. **Token-compact.** Minimal syntax noise.
7. **Auditable on demand.** A human can inspect any program through a viewer, even though nobody writes it by hand.

**Non-goals:** human ergonomics for writing, raw performance in v0.1, and replacing existing languages in general.

---

## 3. Language Model

### 3.1 Programs are typed graphs

A Mizan program is a graph of typed nodes, stored in a compact binary or structured form, not in a text file with syntax.

- Nodes are operations. Edges are data flow.
- The AI emits nodes through a constrained schema, so a **syntax error cannot exist**.
- Formatting, comments-for-humans, and naming style are not part of the language.

### 3.2 Strong static types

Every node has input and output types. The interpreter type-checks the full graph before execution. There are no implicit conversions.

### 3.3 Explicit effects

Any operation that touches the outside world (database, network, filesystem, clock, randomness) is a declared **effect**. Pure computation has no effects.

Each function declares its effect set, for example `[db.read]` or `[db.read, db.write, net.http]`. The interpreter can:

- refuse to run a program that uses an effect it was not granted,
- show a human the complete list of side effects before approval,
- replay or mock effects for testing.

### 3.3.1 Determinism

Randomness and time are effects, so a pure function is fully reproducible. Given the same inputs and the same recorded effect results, a program produces the same output.

### 3.4 Contracts

Every function carries:

- **Preconditions** (what must be true of the input),
- **Postconditions** (what must be true of the output),
- optionally **invariants** over state.

Contracts are checked at load time where they can be proven, and at run time otherwise. A contract failure stops execution with a precise, machine-readable error that the AI can use to repair its own program.

### 3.5 Content addressing

Each function is identified by a hash of its normalized graph, not by a name. This removes naming conflicts and version ambiguity, makes caching and sharing trivial, and lets the AI reuse existing verified functions by reference. (This idea comes from Unison.)

### 3.6 Token-compact encoding

The wire format uses short opcodes and no keywords or whitespace. The goal is to lower generation cost and latency, and to reduce the surface for mistakes.

---

## 4. Execution Model

```
  Human intent (prompt / spec / tests)
              |
              v
   AI generates Mizan graph
              |
              v
   1. Schema validation   (well-formed nodes only)
   2. Type check          (all edges consistent)
   3. Effect check        (granted vs requested effects)
   4. Contract check      (prove statically, or instrument)
   5. Test run            (spec examples and property tests)
              |
        pass? |--- no --> structured error returned to AI --> repair loop
              |
             yes
              v
   Sandboxed execution (only granted effects)
              |
              v
   Result + audit log
```

Key property: **the repair loop is machine-to-machine.** Errors are structured data, not text for humans, so the AI can fix its own output without a person in the middle.

---

## 5. Where Humans Fit

"Humans never need to read the code" does not mean "humans never need control." Unreadable code that handles money or security is a risk. Mizan moves the human's attention from the **implementation** to three places:

1. **Intent.** The spec, written in plain language or a structured form.
2. **Verification.** The tests and contracts that define "correct."
3. **Authority.** The effect permissions the program is granted.

A **read-only viewer** renders any graph into human-readable form for audit, debugging, and compliance. Humans do not write through the viewer. They read through it.

---

## 6. Example (debug rendering)

The following is a debug view, not source code. No human writes it.

```
fn #a91f
  in:   Partner(id: Int)
  out:  Money
  fx:   [db.read]
  pre:  id > 0
  post: out >= 0
  body: sum(map(invoice.amount,
                filter(invoice.partner == id, db.invoices)))
```

What the interpreter can conclude before running it:

- It reads the database and nothing else (no network, no writes).
- It returns a non-negative amount, or the run is stopped.
- Its identity is `#a91f`. If another function has the same meaning, it has the same hash.

### 6.1 ERP-flavored illustration

For ERP systems (such as Odoo), many bugs live in business rules around accounting, taxes, and stock. A contract-carrying function would state the rule that must hold, for example "total debit equals total credit for a journal entry," and the interpreter would enforce it on every run, regardless of who or what wrote the code.

---

## 7. The Bootstrapping Problem

AI writes best in languages it has seen millions of examples of. A new language has none. This is the main practical risk, and the plan is staged:

1. **In-context learning.** Give the model a short spec and examples in the prompt. This works reasonably for small, regular languages.
2. **Transpile first.** Let the AI write in a familiar language (Python), then compile that to Mizan. This produces training pairs.
3. **Fine-tune.** Train on the verified pairs so the model writes Mizan natively.
4. **Verifier as teacher.** The type, effect, and contract checks provide a cheap, automatic feedback signal for improving generation.

---

## 8. Risks and Limitations

- **Bootstrapping cost** (section 7) may dominate early results.
- **Auditability.** If the viewer is weak, the "no human reads it" model becomes unsafe. The viewer is a core component, not an add-on.
- **Contracts can be wrong.** A verified program that matches a wrong spec is still wrong. The spec is the new place for bugs.
- **Proof limits.** Not every contract can be proven statically, so some checks stay at run time.
- **Performance.** An interpreter is slower than compiled code. v0.1 does not target speed.
- **Ecosystem.** Libraries, integrations, and tooling do not exist yet.
- **Unproven claim.** It is not established that a graph form outperforms good Python plus a strong type checker and tests. Measuring this is a main goal of the prototype.

---

## 9. Related Work

This design combines existing ideas and does not claim they are new:

- **Unison**: content-addressed code.
- **WebAssembly and LLVM IR**: compact, machine-oriented program formats.
- **Lean, Coq, Dafny**: machine-checked specifications and proofs.
- **Design by Contract (Eiffel)**: pre/postconditions as part of code.
- **Effect systems** (Koka, Haskell-style IO tracking): declared side effects.
- **Structured/constrained decoding**: forcing model output to match a schema.

---

## 10. Prototype Roadmap

| Phase | Deliverable |
|---|---|
| 0 | This paper and a minimal spec of nodes, types, and effects |
| 1 | A small Python interpreter that runs typed graphs with contracts |
| 2 | Effect system and sandbox (db, file, http as mockable effects) |
| 3 | Human viewer that renders a graph as readable text |
| 4 | LLM loop: prompt to graph to check to repair to run |
| 5 | Benchmark against "AI writes Python plus tests" on the same tasks |
| 6 | Odoo experiment: generate and verify a small addon rule set |

**Success criterion for phase 5:** on a fixed set of tasks, Mizan has a lower rate of incorrect-but-accepted programs than the Python baseline, at comparable or lower token cost. If it does not, the idea is wrong and the paper should say so.

---

## 11. Open Questions

1. What is the smallest set of node types that is still useful?
2. Binary graph or structured text (like JSON/S-expressions) as the first encoding?
3. How much of contract checking can be static in v0.1?
4. How should the viewer present large graphs so a human can audit them quickly?
5. Can the verifier signal be used to train models directly?

---

## 12. Conclusion

If AI becomes the main author of software, the language should be built around the author's strengths and weaknesses. Mizan proposes a typed graph with declared effects, contracts, determinism, and content addressing, run by an interpreter that gives the AI structured feedback. Humans define intent and authority, and audit through a viewer. The idea is testable with a small prototype, and the first step is to build it and measure it against a plain Python baseline.

---

*Draft v0.1. Feedback and pull requests are welcome.*
