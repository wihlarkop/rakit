# SQLAlchemy Core parity finishing plan

**Goal:** Make PR #60 merge-ready while preserving truthful capability advertisement and the existing backend-neutral public write architecture.

## Task 1: Close optimistic-concurrency fail-closed gaps

- Keep the existing sane-rowcount decision path.
- Reject empty optimistic predicates before UPDATE/DELETE.
- Reject empty next-values before optimistic UPDATE.
- Use the existing RED guardrail tests as the regression proof.

## Task 2: Reach Core writes through the existing public seam

- Install `SQLAlchemyCoreWriteServiceProvider` on `ResourceAdapterRuntime`.
- Keep `form_routes.GraphMutationService` as the public graph-write API.
- Do not add a parallel HTTP or persistence API.

## Task 3: Preserve one graph mutation claim and authorization boundary

- Add the explicit handoff for a parent already atomically claimed by the scalar update.
- Validate relationship concurrency proof before that parent claim.
- Preserve scoped target resolution and one root Core UoW.
- Require exact relationship-operation capabilities and exact target create/update/delete capabilities when such steps are present.
- Keep unsupported direct child mutation shapes fail-closed.

## Task 4: Prove public Core graph writes

- Add regression coverage through `WriteResourceBinding` / `build_write_routes`, not only direct adapter service calls.
- Prove scalar + relationship update commits together.
- Prove stale relationship state does not partially persist.
- Prove mapping-backed Core records render existing scalar form values correctly.

## Task 5: Promote capabilities only after behavioral proof

- Run targeted Core tests and capability conformance.
- Run formatter, lint, type checking, full suite, lowest-direct, latest-allowed, artifact and release gates.
- Only then make the 5/5 advertisement and matrix expectations consistent.

## Task 6: Final exact-head verification and merge

- Review the final diff for architecture/security regressions.
- Require exact-head CI to be fully green.
- If no correctness or security uncertainty remains, mark PR ready and squash-merge to `main`.
- Fetch and report the canonical post-merge `main` SHA.
