# scripts/

Operational scripts for the SolGuard monorepo.

| Script | Purpose | When to run |
|--------|---------|-------------|
| `setup.sh` | One-shot environment bootstrap: copies `.env`, installs Node + Python deps, runs Phase 1 verification. | First clone, fresh machine. |
| `verify-phase1.sh` | Phase 1 (M0) acceptance gate — required before moving to Phase 2. | Anytime, CI, before commit. |

Phase 2+ scripts (`run_benchmark.py`, `deploy.sh`, …) will be added as
their respective phases land.
