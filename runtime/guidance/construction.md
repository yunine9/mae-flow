# Construction

Implement the approved behavior one coherent CP at a time.

- For a localized change with a concise confirmed scope, proceed directly. Upgrade to Full when semantic risk reveals unclear behavior, cross-module design, compatibility, security, data, public interface, shared state, or concurrency concerns. This decision is not file or line count.
- Confirm the current behavior boundary and fix the root cause instead of masking a symptom.
- Use the simplest design that is clear under actual constraints. Reuse existing components and prefer the standard library; avoid duplicate mechanisms and speculative abstraction.
- Keep dependency direction and ownership explicit. Define error propagation, cleanup, resource lifetime, concurrency, compatibility, and public behavior at the boundary.
- Create each planned test seam during coding. Extract deterministic decisions from framework boundary plumbing so the later formal UT can control inputs and observe outputs without imitating the framework.
- Keep the seam narrow and production-meaningful. Do not add a public hook used only by tests or mock stable infrastructure merely to increase coverage.
- Run low-cost checks for the touched code and repair safe local issues. Leave high-risk restructuring visible for quality disposition.
- Give every supplied review item a disposition: fixed, unsupported with evidence, design tradeoff, or out of scope. Do not require a report schema and do not launch a reviewer loop.
- After review fixes, invoke the Intake-confirmed Build route synchronously once for this CP. `build-fix` is a C++ option, not a universal command; Java normally uses the confirmed Maven compile command, and other languages use their confirmed repository Skill or command. Never use delay loops, repeated status probes, detached execution, or automatic Build retry.
- When coding reveals an implementation deviation, record it and compare it with the confirmed Spec and behavior baseline. Align the implementation when the artifacts remain correct; otherwise propose an artifact update for user review. Never silently rewrite either authority.

Construction records natural-language UT handoff facts: behavior completed, deterministic logic, seam created, real framework boundary retained, and implementation deviation. A CP does not write or run formal UT; its configured Build provides the one compile attempt for that CP.

For each Full CP, keep four short recoverable facts: its confirmed brief, actual result, one-pass CODE Reviewer conclusion, and incremental UT intent. The CP card shows those facts together with the next CP brief, and the user may revise the next design in natural language. These facts are guidance, not a fixed report schema or a new coding-plan file.
