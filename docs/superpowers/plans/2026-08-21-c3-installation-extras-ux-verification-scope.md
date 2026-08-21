# C3 Source Smoke Scope

The temporary source smoke deliberately runs before C3 regression tests are changed. It verifies source behavior without pytest:

- locked workspace installation;
- exact canonical optional-dependency metadata;
- server-neutral `standard` membership;
- deterministic/deduplicated install vocabulary;
- rejection of raw non-canonical extra identifiers;
- all four C2 starter/server dependency combinations;
- capability-specific optional-facade install hints;
- transitive import failure passthrough;
- absence of the unpublished `server-uvicorn` alias from active metadata/source/getting-started docs.

The temporary workflow must be deleted before final CI and must not appear in the final C3 diff.
