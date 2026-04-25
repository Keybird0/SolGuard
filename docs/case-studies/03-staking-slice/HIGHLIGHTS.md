# Case 03 Highlights — Staking Slice (312-line Anchor + legacy-path program)

## Why this case was picked

"Does SolGuard scale?" This fixture is a 312-line program that intentionally mixes idiomatic Anchor with a hand-rolled `AccountInfo` migration path — the kind of hybrid you'll find in any production staking protocol that predates Anchor 0.27. It's the stress test for the detector's cross-cutting ability.

## What SolGuard did well

- **Found the exploit chain, not just the symptoms.** The report pins **both** halves of the spoof path (missing owner check at line 251 + raw `try_from_slice` at line 129) and explicitly says they compose into a two-step attack.
- **Clustered the findings.** The cross-cutting observation notes all three findings live in the same ~30-line legacy-migration block — so reviewers see *one* bug zone, not three unrelated issues.
- **Honest about confidence.** The Medium overflow finding is marked `review` with the note that today's upstream cap makes it a false positive, but the pattern is brittle. That nuance would be hard to extract from a pure rule-based tool.
- **Scaled to 19 seconds** end-to-end for a 312-line contract with 6 handlers.

## Where SolGuard could improve

- The overflow finding is a **known false positive** in this snapshot (the upstream `u8` cap bounds the product). SolGuard surfaces this honestly but cannot yet eliminate it — that requires data-flow analysis across module boundaries, which is on the Q3 2026 roadmap.
- We do not yet reason about upgrade-authority control flow; for production staking programs, that's the single most important governance property to audit.

## Takeaway for evaluators

A 312-line hybrid program, three findings delivered in 19 seconds, with the exploit chain reconstructed end-to-end and a concrete remediation plan. This is the surface area where professional audits typically charge $40–60k — SolGuard delivers a credible first pass for under a cent of compute.
