# Construction

Implement the approved behavior one coherent CP at a time.

- Confirm the current behavior boundary and fix the root cause instead of masking a symptom.
- Use the simplest design that is clear under actual constraints. Reuse existing components and prefer the standard library; avoid duplicate mechanisms and speculative abstraction.
- Keep dependency direction and ownership explicit. Define error propagation, cleanup, resource lifetime, concurrency, compatibility, and public behavior at the boundary.
- Create each planned test seam during coding. Extract deterministic decisions from framework boundary plumbing so the later formal UT can control inputs and observe outputs without imitating the framework.
- Keep the seam narrow and production-meaningful. Do not add a public hook used only by tests or mock stable infrastructure merely to increase coverage.
- Run low-cost checks for the touched code and repair safe local issues. Leave high-risk restructuring visible for quality disposition.

Construction records natural-language UT handoff facts: behavior completed, deterministic logic, seam created, real framework boundary retained, and implementation deviation. A CP does not write, compile, or run formal UT.
