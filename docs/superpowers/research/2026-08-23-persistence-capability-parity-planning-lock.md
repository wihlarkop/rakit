# Persistence Capability Parity — Planning Lock

**Status:** Locked / approved for implementation-plan drafting

**Date:** 2026-08-23

**Branch:** `research/persistence-capability-parity`

## Authority

This addendum closes the planning items that were still marked Pending at the end of:

`docs/superpowers/research/2026-08-23-persistence-capability-parity.md`

The approved design is now authoritative for implementation ordering, shared conformance requirements, compatibility gates, and workstream boundaries:

`docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

The provider evidence and provider-specific decision records in the original research document remain unchanged and continue to be the evidence source behind the design.

## Locked completion state

```text
SQLAlchemy Core provider research   Complete / locked
Tortoise provider research          Complete / locked
Peewee provider research            Complete / locked
Piccolo provider research           Complete / locked
Cross-provider neutral comparison   Complete / locked
Implementation ordering             Complete / locked
Shared conformance matrix           Complete / locked
Compatibility decision boundaries   Complete / locked
Implementation plan                 Not written yet
Runtime implementation              Not started
Capability promotion                Not started
```

## Locked implementation order

```text
P0 Shared acceptance contract
P1 SQLAlchemy Core
P2 Tortoise ORM
P3 Piccolo ORM
P4 Peewee Async ORM
P5 Cross-provider closure
```

Within each provider:

```text
atomic optimistic source
-> source/non-test verification
-> relationships source
-> graph/non-test verification
-> permanent regression/conformance
-> compatibility matrix
-> capability promotion
-> exact-head CI/review
-> squash merge
```

## Locked compatibility boundaries

- SQLAlchemy Core: ambiguous physical relationship paths require explicit adapter-local binding; atomic success requires sane rowcount semantics.
- Tortoise: version-column concurrency is the initial target; affected-row behavior and snapshot/no-op semantics remain backend-gated; association objects require explicit Tortoise models.
- Piccolo: current `piccolo>=1.30,<2` floor remains; atomic success uses `RETURNING(identity)`; SQLite RETURNING and Cockroach M2M paths are explicit conformance gates.
- Peewee: parity implementation proposes `peewee>=4.0.8,<5`; async SQLite, asyncpg, and aiomysql behavior must be proven before global atomic capability promotion.

## Scope boundaries

- D3 remains Complete and is not reopened.
- SQLAlchemy ORM remains the default/reference provider.
- Existing neutral core relationship, concurrency, identity, and UoW contracts remain authoritative.
- No universal persistence DSL, fake ORM, shared rowcount layer, or speculative core redesign is approved.
- Masonite remains deferred.
- Authentication-provider parity is outside this workstream and requires separate evaluation if desired later.
- No release, tag, TestPyPI, PyPI, or package publication is approved.

## Next gate

The next artifact may be the detailed implementation plan only after the maintainer reviews the written design spec. Runtime/source implementation begins only after that implementation plan is approved.
