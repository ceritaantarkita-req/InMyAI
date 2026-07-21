# How to Add a Local Tool

1. Decide whether the task can be deterministic instead of using an LLM.
2. Define input and output schemas.
3. Add permission scope: read, propose, write, execute, or destructive.
4. Validate and canonicalize all paths.
5. Add resource estimates and cancellation/timeouts.
6. Return evidence rather than only prose.
7. Add audit logging.
8. Add failure states that do not silently fall back to unsafe behavior.
9. Write unit/integration tests using synthetic data.
10. Document operating-system requirements and update the public capability matrix.
