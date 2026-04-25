# Case 01 Highlights — Arbitrary CPI (51-line Anchor program)

## Why this case was picked

"Small contract, critical bug." It maps 1:1 to Sealevel-Attacks §5 — the textbook arbitrary CPI — so anyone familiar with Solana security literature can sanity-check the output in 30 seconds.

## What SolGuard did well

- **1 Critical finding, zero false positives, zero missed findings** against the canonical ground-truth — tight precision on the highest-severity class.
- **Exact line number** (`line 23`) and **exact rule ID** (`arbitrary_cpi`) returned; the explanation names the missing control (`require_keys_eq!` or `Program<'info, Token>`).
- **Two remediation paths** suggested — the Anchor-idiomatic fix (`anchor_spl::token::transfer`) and the defensive-check fallback — so teams constrained to raw `invoke` still have a one-liner.
- **End-to-end < 13 seconds** from submission to completed 3-tier report (LLM-warm run).

## Where SolGuard could improve

- The detector flagged line 23 (the `instruction::transfer` call) rather than line 33 (the `invoke(...)` call). Both are part of the same exploit chain, but some auditors expect the pin to be at the sink. This is tracked in `outputs/phase6-fp-fn-analysis.md` as an off-by-one location issue that Round 3 prompt tuning will address.

## Takeaway for evaluators

A single Critical finding with full reasoning, exploit path, and fix — delivered in 13 seconds for roughly $0.01 of compute. That is the SolGuard promise at its smallest surface area.
