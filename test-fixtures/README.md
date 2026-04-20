# Test Fixtures · Ground Truth

Synthetic Solana/Anchor contracts used to exercise the SolGuard rule set.
Each file is annotated at the top with the **expected rule id**, **severity**,
and **approximate line number** of the defect so regression tests can
assert precise matches.

> These fixtures **do not** build under `cargo` — they are minimal
> standalone files. The scanner reads them as text.

---

## Seed corpus (Phase 1)

| # | File | Rule | Severity | Lines | Expected Hits |
|---|------|------|----------|-------|---------------|
| 1 | `contracts/01_missing_signer.rs`  | `missing_signer_check` | High     | ~25 | 1 |
| 2 | `contracts/02_missing_owner.rs`   | `missing_owner_check`  | High     | ~30 | 1 |
| 3 | `contracts/03_integer_overflow.rs`| `integer_overflow`     | Medium   | ~32 | 2 |
| 4 | `contracts/04_arbitrary_cpi.rs`   | `arbitrary_cpi`        | Critical | ~42 | 1 |
| 5 | `contracts/05_clean_contract.rs`  | *(none)*               | —        | ~90 | **0** (negative test) |

Total: **5 fixtures · 4 vulnerable + 1 clean**.

---

## Benchmark corpus (Phase 6)

Phase 6 expands this to **10+ real-world Anchor programs** in
`real-world/{small,medium,large}/`. Each contract there is paired with a
`ground_truth.yaml` enumerating the known vulnerabilities (or asserting
`expected: []` for clean code). See
`docs/04-SolGuard项目管理/07-Phase6-测试与优化.md` for the plan.

---

## Conventions

- **Filename**: `NN_rule_short_name.rs` (zero-padded index for sort).
- **Top-of-file banner** must contain:
  - `Expected rule:` (the `rule_id` that should fire)
  - `Expected severity:` (High / Medium / …)
  - `Expected location:` (line range)
- **One defect per file** for seed fixtures (keeps regression clean).
  Benchmark fixtures in `real-world/` may contain multiple defects.
- **Clean contracts** must declare `Expected rule hits: zero` so the
  false-positive suite can assert an empty `findings` list.

---

## Running against a fixture

```bash
# Phase 2 onwards:
oh -p "audit test-fixtures/contracts/01_missing_signer.rs with solana-security-audit-skill"
```

Expected shape of the JSON report:

```json
{
  "findings": [
    {
      "rule_id": "missing_signer_check",
      "severity": "High",
      "location": "01_missing_signer.rs:25"
    }
  ],
  "statistics": { "high": 1, "total": 1 }
}
```
