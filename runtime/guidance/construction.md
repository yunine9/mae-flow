# Construction Guidance

The main Agent implements the complete approved change from local `spec.md` and `story.md`; no implementation subagent or batch plan is used. Within that single pass, write chunk by chunk following the task order in `implementation.md`: after each chunk, self-check the four items (neighbor-consistent naming, no duplicated helpers, error handling matching the module's convention, downstream interface signatures finalized) before the next chunk, and re-read the whole diff once at the end for cross-chunk drift. Chunks are an in-context discipline only — no compiles, no done, no user contact between them.

Before writing, read the materialized `standards/code-taste-v1.md` and `standards/comment-standard-v1.md`, and study neighboring code first: conformance to the repository's existing abstractions, naming and error-handling conventions outranks self-contained novelty. The taste baseline is a target, not a gate; the craft reviewer and the human review judge against it.

For a localized change with concise confirmed scope, proceed directly. Upgrade to full workflow when semantic risk appears: unclear behavior, cross-module impact, compatibility, security, data, public interface, shared state, or concurrency. The decision follows semantic risk, not file or line count.

During coding, preserve ownership, error, lifetime, concurrency, compatibility, and reuse boundaries. Prefer the standard library, simplest design, and no speculative abstraction. Create a deterministic test seam during coding; isolate each framework boundary and hand the complete change to formal UT later.

If implementation exposes a real deviation from the confirmed Spec or Story, record the implementation deviation and compare it with the behavior baseline. Align the implementation when possible; otherwise propose an artifact update for user judgment. Never silently rewrite confirmed behavior.

Compilation is mandatory and delegated to compile-agent. Its generated task card must identify the exact project root, changed source/build files, execution roots, and configured build Skill or command. The main Agent must not replace this evidence with an ad-hoc local build.

Keep code uncommitted for the optional one-time read-only CODE Agent precheck and the user's IDE review. Revisions return to main-Agent editing and compile-agent verification before another user review.
