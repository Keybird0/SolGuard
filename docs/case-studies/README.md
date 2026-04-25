# SolGuard Case Studies

Three real-world(-ish) SolGuard audit reports, each showcasing a different mode of the tool.
These are the same reports the Vercel Demo Mode replays step-by-step — the user interface drives through them when there is no backend available.

---

## 01 — Arbitrary CPI (51-line Anchor program)

**Highlight**: Small contract, one Critical finding, zero false positives. A clean single-shot hit.

- [`risk_summary.md`](./01-multi-vuln-cpi/risk_summary.md) · [`assessment.md`](./01-multi-vuln-cpi/assessment.md) · [`checklist.md`](./01-multi-vuln-cpi/checklist.md) · [`report.json`](./01-multi-vuln-cpi/report.json)
- **Why it matters**: [HIGHLIGHTS.md](./01-multi-vuln-cpi/HIGHLIGHTS.md)
- **Source fixture**: [`test-fixtures/real-world/small/rw04_arbitrary_cpi.rs`](../../test-fixtures/real-world/small/rw04_arbitrary_cpi.rs) (adapted from `coral-xyz/sealevel-attacks@24555d0`)
- **Numbers**: 1 Critical · 0 High · 0 Medium · 13 seconds

---

## 02 — Clean Escrow (172-line Anchor program)

**Highlight**: Zero findings. A clean bill of health is SolGuard's hardest test because any false positive breaks trust faster than a missed bug.

- [`risk_summary.md`](./02-clean-escrow/risk_summary.md) · [`assessment.md`](./02-clean-escrow/assessment.md) · [`checklist.md`](./02-clean-escrow/checklist.md) · [`report.json`](./02-clean-escrow/report.json)
- **Why it matters**: [HIGHLIGHTS.md](./02-clean-escrow/HIGHLIGHTS.md)
- **Source fixture**: [`test-fixtures/real-world/medium/rw08_clean_escrow.rs`](../../test-fixtures/real-world/medium/rw08_clean_escrow.rs)
- **Numbers**: 0 findings · 6 seconds

---

## 03 — Staking Slice (312-line mixed Anchor + legacy program)

**Highlight**: Production-style hybrid contract. Detects a two-step spoof chain and clusters three findings into one ~30-line "bad zone" so auditors see the bug region at a glance.

- [`risk_summary.md`](./03-staking-slice/risk_summary.md) · [`assessment.md`](./03-staking-slice/assessment.md) · [`checklist.md`](./03-staking-slice/checklist.md) · [`report.json`](./03-staking-slice/report.json)
- **Why it matters**: [HIGHLIGHTS.md](./03-staking-slice/HIGHLIGHTS.md)
- **Source fixture**: [`test-fixtures/real-world/large/rw12_staking_slice.rs`](../../test-fixtures/real-world/large/rw12_staking_slice.rs)
- **Numbers**: 2 High · 1 Medium · 19 seconds

---

## Reading the reports

Every case has the same three-tier structure the SolGuard Skill always emits:

| File | Audience | Length |
|---|---|---|
| `risk_summary.md` | Executive / founder | ≤ 1 page |
| `assessment.md` | Technical lead / auditor | detailed reasoning + code |
| `checklist.md` | Implementer | concrete remediation tasks |

The `report.json` is the machine-readable version of the above — that is what the Express backend returns from `GET /api/audit/:id/report.json` and what the UI uses to render the findings-count badges.

## Reproducing these reports

The fixtures and their ground truth labels live in `test-fixtures/real-world/` with Phase 6's `benchmark.yaml`. To reproduce:

```bash
cd SolGuard/skill/solana-security-audit-skill
uv run python ../../scripts/run_benchmark.py \
    --fixtures rw04_arbitrary_cpi,rw08_clean_escrow,rw12_staking_slice \
    --output ../../outputs/phase7-reproduce
```

The resulting `outputs/phase7-reproduce/audits/*/risk_summary.md` should line up with these case studies modulo LLM non-determinism (prompt temperature 0.05, but still not bit-for-bit identical).
