# Story Design

Treat the approved Spec as the WHAT authority. Story defines HOW the observable behavior will be implemented; do not reopen confirmed product decisions unless code evidence exposes a real contradiction.

- Identify the implementation boundary, main code locations, interfaces, dependencies, and data flow.
- Make ownership, error semantics, resource lifetime, concurrency, compatibility, and cleanup explicit.
- Separate stable framework plumbing from changing business decisions. Prefer deterministic business units behind narrow adapters.
- Name the test seam that must be created during coding, the observable it exposes, and the real boundary that remains integrated. Do not postpone this decision until formal testing.
- Prefer reuse and the standard library where they fit. Choose the simplest design that satisfies current constraints and avoid speculative abstraction.
- Divide construction into coherent behavior checkpoints. Each checkpoint states its outcome, files likely to change, key design action, testability work, completion evidence, and risk.

A Full Story receives one focused design review. Present real tradeoffs to the user; ordinary reviewer approval continues without ceremony.
