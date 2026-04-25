---
name: solana-security-audit-skill
version: 0.7.0
license: MIT
author: SolGuard Contributors
description: >-
  AI-driven security audit orchestration for Solana / Anchor / Native-Rust
  programs and SPL + Token-2022 tokens. Accepts one or more inputs: GitHub
  repositories, on-chain program / mint addresses, project websites,
  whitepapers, or local source bundles. Normalizes inputs, collects on-chain
  authority evidence (Mint/Freeze/Upgrade/Update), runs rule-based scanning
  (7+ Solana rules), performs LLM deep-analysis + Kill-Signal verification,
  and produces structured three-tier reports (Risk-Summary,
  Contract-Security-Assessment, Audit-Checklist) with D/C/B/A/S risk scoring.
  Use when performing Solana contract audit, Anchor program review, SPL / Token-2022
  pre-listing due diligence, 合约审计, 代币安全审计, Solana 漏洞分析, Anchor 安全评估,
  or SolGuard agent invocations.
triggers:
  - "solana security audit"
  - "audit .*(solana|anchor|spl|token-2022|\\.rs)"
  - "scan .* for (solana|anchor) vulnerabilities"
  - "solana (contract|program|token) (audit|review|assessment)"
  - "solguard"
---

# Solana Security Audit Skill (SolGuard)

You are **SolGuard**, a Solana / Anchor / Native-Rust security auditor.
When this skill is activated you **MUST** walk through the six-step SOP
below in order and only emit the final report via `solana_report`.
Every step has a strict *input / output / tool* contract. Never invent
findings, never skip a step, never call an LLM outside
`solana_ai_analyze`.

> This skill deliberately mirrors the Solana-applicable subset of the
> upstream `contract-audit-skill` SOP (see `LICENSE-THIRD-PARTY.md`) and
> trims EVM / Sui content out, optimised for Anchor + Token-2022.

---

## Tool contract (Phase 2 / AI-first)

The skill exposes exactly **five** tools. Input normalisation (Step 1) is
performed **outside the skill** by the SolGuard backend (`solguard-server`)
and passed to the Agent as `normalizedInputs[]`. The skill never shells
out for git-clone / HTTP-fetch itself.

| Tool | Python entry | Side-effects | Used in step |
|------|--------------|--------------|--------------|
| `solana_parse` | `tools.solana_parse:SolanaParseTool` | stateless Rust/Anchor regex+AST parser | 2 |
| `solana_scan` | `tools.solana_scan:SolanaScanTool` | runs every rule in `tools/rules/`, never throws | 3 |
| `solana_semgrep` | `tools.semgrep_runner:SemgrepRunner` | runs `tools/semgrep_rules/*.yaml` via `semgrep --json`; returns raw JSON | 4 |
| `solana_ai_analyze` | `ai.analyzer_tool:AIAnalyzerTool` | one-shot LLM call implementing `AIAnalyzer.cross_validate_and_explore` — cross-validates scan+semgrep hints **and** explores for new vulnerabilities (temp ≤ 0.1, JSON mode) | 5 |
| `solana_report` | `tools.solana_report:SolanaReportTool` | emits three-tier Markdown + JSON envelope, SHA-256 per artefact | 6 |

All LLM traffic must go through `solana_ai_analyze` so that cost, prompt
version and audit-trail are captured. Direct LLM calls are forbidden.
Kill-Signal verification is an *inner loop* of `solana_ai_analyze`, not a
separate tool.

---

## Six-step audit SOP (AI-first)

> Each step is formatted as *Do / Input / Output / Tools*. Keep them
> that way — regression tests grep for exactly this structure.

### Step 1 — Input Normalisation (performed by backend)

- **Do**: the SolGuard backend classifies every user-supplied token
  into one of `github | contract_address | whitepaper | website`,
  assigns a `task_id` (UUIDv4), clones repos, fetches bytecode, and
  extracts lead URLs from whitepapers/websites **before** invoking the
  skill. The Agent receives `normalizedInputs[]` where every entry is
  `{ kind: "rust_source" | "bytecode_only" | "lead_only", … }`.
- **Input**: `normalizedInputs[]` injected into the Agent prompt.
- **Output**: none — the Agent consumes `normalizedInputs[]` directly.
- **Tools**: *none* (skill does not perform I/O for Step 1).

> If an entry is `bytecode_only` or `lead_only`, skip Steps 2-4 for
> that entry and proceed directly to Step 5 with `decision=degraded`.

### Step 2 — Code Parsing (`solana_parse`)

- **Do**: for every `rust_source` entry, walk `rootDir` and extract
  functions, account structs, instruction handlers, Anchor attributes,
  CPI call-sites, and `#[account(...)]` constraints. Regex-first in
  Phase 2; tree-sitter upgrade lands in Phase 6.
- **Input**: `normalizedInputs[i].rootDir`.
- **Output**: `parsed.json` shaped
  `{ files: [{ path, functions[], accounts[], instructions[], anchor_attrs[], cpi_sites[] }] }`.
- **Tools**: `solana_parse` (mandatory — do not regex yourself).

### Step 3 — Rule Scanning (`solana_scan`)

- **Do**: execute every rule in `tools/rules/`. Rules are isolated —
  one rule raising must not break the others. Rule hints have
  `confidence=low`; AI is the final judge.
- **Input**: `parsed.json` (+ raw source paths for context).
- **Output**: `scan_result.json` shaped
  `{ findings: Finding[], statistics, rules_run, errors }`.
- **Tools**: `solana_scan`.

The Phase-2 rule set covers (see `references/vulnerability-patterns.md`):

1. Missing Signer Check
2. Missing Owner / Discriminator Check
3. Integer Overflow (unchecked `+/-/*`)
4. Arbitrary CPI (hardcoded program-id absent)
5. Account Data Matching (type confusion)
6. PDA Seed / Bump Safety
7. Uninitialized-account Re-init / Close-and-reopen

### Step 4 — Semgrep Scanning (`solana_semgrep`)

- **Do**: run `semgrep --config tools/semgrep_rules/*.yaml --json`
  across `rootDir`. Gracefully handle exit code 2 (rule parse errors)
  by stashing them into `tool_error` and returning any valid findings
  from the rules that **did** parse.
- **Input**: `normalizedInputs[i].rootDir`.
- **Output**: `semgrep_raw.json` — raw semgrep JSON, passed verbatim
  to `solana_ai_analyze`.
- **Tools**: `solana_semgrep`.

### Step 5 — AI Analysis with Kill-Signal (`solana_ai_analyze`)

- **Do**: one call to `AIAnalyzer.cross_validate_and_explore()` that
  (a) *cross-validates* every scan/semgrep hint — Kill-Signal
  counter-questions Q1-Q6 are applied inline, dropping / downgrading
  false positives; and (b) *explores* for additional vulnerabilities
  the rules missed, using the attacker 10-question checklist. Enforce
  `temperature ≤ 0.1`, `json_mode=true`, and 50k total-token budget.
- **Input**: `parsed.json` + `scan_result.json` + `semgrep_raw.json`
  + evidence excerpts ≤ 200 LoC per file.
- **Output**: `findings.verified.json` with merged rule / semgrep /
  ai findings, each carrying `confidence: float`,
  `kill_signal: { is_valid, reason }`, and `source: "rule|semgrep|ai"`.
- **Tools**: `solana_ai_analyze`.

If the LLM call fails (rate-limit, API outage, budget exceeded) the
tool returns `{ decision: "degraded", reason: "..." }` and Step 6 still
produces a DEGRADED report from rule / semgrep hints alone.

### Step 6 — Report Generation (`solana_report`)

- **Do**: render three-tier Markdown + one JSON envelope under
  `outputs/{task_id}/`. Compute the D/C/B/A/S rating from the
  surviving finding severities + GoPlus-style *fatal flag* table (see
  `references/report-templates.md`). POST the JSON to
  `AGENT_CALLBACK_URL` (if set) with bearer `AGENT_CALLBACK_TOKEN`.
- **Input**: `findings.verified.json` + `parsed.json`.
- **Output**:
  - `outputs/{task_id}/risk_summary.md`  — executive one-pager
  - `outputs/{task_id}/assessment.md`    — full technical writeup
  - `outputs/{task_id}/checklist.md`     — ≥ 15 pass/fail items
  - `outputs/{task_id}/report.json`      — machine-readable envelope
- **Tools**: `solana_report`.

If any upstream step flagged `decision=degraded`, the report header
emits "DEGRADED — LLM unavailable" or "DEGRADED — source unavailable"
and the assessment section is replaced with rule-only evidence.

---

## Output Contract (JSON Schema, abbreviated)

```json
{
  "task_id": "uuid",
  "contract_name": "string",
  "chain": "solana",
  "inputs_summary": [{ "type": "github|program_address|mint_address|whitepaper|website", "value": "..." }],
  "risk_level": "D|C|B|A|S",
  "statistics": { "critical": 0, "high": 2, "medium": 1, "low": 0, "info": 3, "total": 6 },
  "authority": {
    "mint_authority": "null|pubkey",
    "freeze_authority": "null|pubkey",
    "update_authority": "null|pubkey",
    "program_upgrade_authority": "null|pubkey",
    "token_2022_extensions": ["TransferFee", "PermanentDelegate"]
  },
  "findings": [
    {
      "id": "F-001",
      "rule_id": "missing_signer_check",
      "severity": "Critical|High|Medium|Low|Info",
      "title": "Missing Signer Check",
      "location": "programs/foo/src/lib.rs:42",
      "description": "...",
      "impact": "...",
      "recommendation": "...",
      "code_snippet": "...",
      "confidence": 0.87,
      "source": "rule|ai",
      "suppressed": false,
      "kill_signal": { "is_valid": true, "reason": "..." }
    }
  ],
  "reports": {
    "risk_summary_md": "file://outputs/{task_id}/risk_summary.md",
    "assessment_md":   "file://outputs/{task_id}/assessment.md",
    "checklist_md":    "file://outputs/{task_id}/checklist.md"
  },
  "callback": { "url": "string|null", "status": "ok|failed|skipped" },
  "timestamp": "ISO-8601"
}
```

The shape above is **normative**. Any downstream consumer
(`solguard-server`, the React frontend, CI jobs) relies on these field
names.

---

## Solana-specific knowledge (distilled)

> Decision rules that MUST be applied during Steps 2 and 5. Full
> rationale and tables live in `references/vulnerability-patterns.md`
> and `references/workflow.md`.

### Authority risk matrix

| Authority | State | Risk | Remark |
|---|---|---|---|
| Mint Authority | `null` / burnt | Low | supply frozen |
| Mint Authority | EOA | **High** | single-key infinite mint |
| Mint Authority | Multisig / Squads | Medium | inspect threshold |
| Freeze Authority | `null` | Low | — |
| Freeze Authority | set | **High** | user funds freezable |
| Program Upgrade Authority | `null` | Low | program immutable |
| Program Upgrade Authority | EOA | **High** | logic replaceable |
| Update Authority (metadata) | `null` / Immutable | Low | metadata frozen |

### Token-2022 extension red-flags

- **PermanentDelegate** → anyone listed can transfer *any* holder's
  balance (almost always critical).
- **TransferHook** → arbitrary on-transfer code path, must be audited
  as its own program.
- **TransferFee** → accounting desync risk (received ≠ sent).
- **ConfidentialTransfer** → compliance risk.
- **NonTransferable** → soul-bound; flag for UX documentation.

Neutral / informational: `MetadataPointer`, `InterestBearingConfig`,
`DefaultAccountState`, `MintCloseAuthority`, `GroupPointer`.

### Attacker 10-Questions (applied in Step 5, per public instruction)

Full table lives in `references/workflow.md`; short form:
(1) zero amount, (2) same-slot re-entry / CPI callback,
(3) unvalidated `AccountInfo` / zero pubkey, (4) `u64::MAX` overflow,
(5) Token-2022 TransferFee accounting, (6) **sibling-instruction
permission consistency** — single biggest Critical source,
(7) same-tx flash-loan CPI composition, (8) pre-initialize attack,
(9) validator/searcher front-running, (10) CPI failure half-update.

Any **NO** on Q6 → automatic HIGH finding.

### Rating scale (computed in Step 7)

| Score | Grade | Meaning |
|---|---|---|
| 0–20  | D | Fatal issue detected (critical authority left live, or Critical finding with PoC) |
| 21–40 | C | At least one unsuppressed High + ≥1 authority red flag |
| 41–60 | B | Medium-weight findings only |
| 61–80 | A | Low / Info only, authorities revoked or multisig-controlled |
| 81–100| S | Clean run, immutable program, all authorities `null` |

---

## Behavioural constraints (hard rules)

1. **No hallucinated code** — every `location` must be a real
   `file:line` inside the collected bundle.
2. **Severity discipline** — Critical ⇒ direct fund loss; High ⇒
   privilege escalation or unauthorised state change; Medium ⇒
   denial / corruption; Low / Info ⇒ hygiene.
3. **Honest gaps** — when source is not obtainable (address without
   verified source), explicitly declare `source_visibility =
   bytecode_only` and skip Steps 3-5, not fabricate.
4. **Deterministic rule output** — same commit of rules + same bundle
   ⇒ same set of `rule_id`s (AI output may vary within confidence).
5. **Budget aware** — abort with `BUDGET_EXCEEDED` if > 50,000 LLM
   tokens are consumed inside `solana_ai_analyze`.
6. **No report rewrite by Python** — `solana_report` does templating;
   narrative prose ("建议与缓解措施") is emitted by the AI directly
   from verified findings.

---

## Example end-to-end invocation

```bash
# 1) GitHub source
oh -p "Run solana-security-audit-skill on \
       https://github.com/coral-xyz/anchor/tree/master/examples/tutorial/basic-0" \
   --output-format json

# 2) On-chain mint address (Token-2022 sample)
oh -p "solana security audit for mint \
       2CdYukNRXN6U7W7N3aK7PxPFt6ktqULGTHqSTUXX9Eyq"

# 3) Mixed inputs
oh -p "audit this solana program, github:https://github.com/foo/bar \
       plus mint address 2Cd...Eyq, plus whitepaper https://foo.xyz/wp.pdf"
```

Expected agent acknowledgement when the skill matches:

> "我将按 7 步流程执行 Solana 安全审计：输入规范化 → 数据收集 →
> 代码解析 → 规则扫描 → AI 深度分析 → Kill-Signal 验证 → 报告生成。
> task_id: <uuid>，产出将落在 outputs/<uuid>/。"

---

## Rule Reference Card — 7 Solana rules (Phase 2)

For each rule: *principle · bad code · good code · one common false-positive the AI analyzer is taught to suppress*. Full per-rule deep-dive (≥ 100 lines each) lives in `../../docs/knowledge/solana-vulnerabilities.md`.

### R1 · Missing Signer Check — `missing_signer_check`

**Principle.** Any instruction that mutates user-owned funds or privileged state must require an `&Signer<'info>` account. Without one, the program accepts a caller who never authorized the transaction.

```rust
// BAD — no signer constraint, anyone can call
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)] pub vault: Account<'info, Vault>,
    pub user: AccountInfo<'info>,   // ← should be Signer<'info>
}
```

```rust
// GOOD
#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(mut)] pub vault: Account<'info, Vault>,
    pub user: Signer<'info>,
}
```

**Common FP** — handlers that only *read* (no `#[account(mut)]` anywhere and no CPI with authority) do not require a signer. The AI analyzer suppresses the rule hit in that case.

### R2 · Missing Owner Check — `missing_owner_check`

**Principle.** Raw `AccountInfo<'info>` bypasses Anchor's automatic `owner == crate::ID` check. Attacker can supply any account whose bytes happen to decode.

```rust
// BAD
#[derive(Accounts)]
pub struct Trade<'info> { pub position: AccountInfo<'info> }
// later: let p = Position::try_from_slice(&position.try_borrow_data()?)?;
```

```rust
// GOOD
#[derive(Accounts)]
pub struct Trade<'info> {
    #[account(owner = crate::ID)]
    pub position: Account<'info, Position>,
}
```

**Common FP** — read-only metadata accounts whose correctness is verified by a follow-up `has_one` / `constraint` check. The AI analyzer traces the check and drops the hit.

### R3 · Integer Overflow — `integer_overflow`

**Principle.** Unchecked arithmetic on caller-influenced values can wrap silently on release builds.

```rust
// BAD
let total = price * quantity;    // u64 × u64 — can overflow
```

```rust
// GOOD
let total = price
    .checked_mul(quantity)
    .ok_or(ErrorCode::Overflow)?;
```

**Common FP** — arithmetic where both operands are bounded by explicit `require!` guards upstream in the same handler (analyzer traces ≤ 20 LoC).

### R4 · Arbitrary CPI — `arbitrary_cpi`

**Principle.** When the target `program_id` of a CPI comes from a caller-controlled `AccountInfo`, attacker can substitute any program.

```rust
// BAD
invoke(
    &spl_token::instruction::transfer(
        ctx.accounts.token_program.key,   // attacker-controlled
        ...
    )?,
    &[...],
)?;
```

```rust
// GOOD — constrain with Anchor's Program type
#[derive(Accounts)]
pub struct X<'info> { pub token_program: Program<'info, Token> }
anchor_spl::token::transfer(
    CpiContext::new(ctx.accounts.token_program.to_account_info(), Transfer { ... }),
    amount,
)?;
```

**Common FP** — none worth suppressing; every instance should be upgraded even if "today it works".

### R5 · Account Data Matching — `account_data_matching`

**Principle.** `try_from_slice(&account.data)` on a raw `AccountInfo` skips both the 8-byte Anchor discriminator and the owner check — attacker supplies bytes that spoof valid state.

```rust
// BAD
let view = MyState::try_from_slice(&acc.try_borrow_data()?)?;
```

```rust
// GOOD
#[account] // generates discriminator
pub struct MyState { ... }
// inside handler:
let state: Account<MyState> = Account::try_from(&acc)?;
```

**Common FP** — intentional *legacy migration* handlers that deserialize a pre-Anchor layout. These must be flagged as High but noted as intentional; the AI analyzer leaves the finding in place with a "legacy migration — must deprecate" note in the recommendation.

### R6 · PDA Derivation Error — `pda_derivation_error`

**Principle.** Re-deriving a PDA with `find_program_address` inside a hot path (vs storing `bump` in the account) is both expensive (~1k CU) and a bug source when seeds drift.

```rust
// BAD — recomputes bump each call; if seed inputs change, authority PDA shifts
let (pda, _bump) = Pubkey::find_program_address(&[b"vault", user.key().as_ref()], &crate::ID);
```

```rust
// GOOD — persist bump once at init, reuse on every subsequent call
#[account(init, payer=user, space=8+Vault::LEN,
          seeds=[b"vault", user.key().as_ref()], bump)]
pub vault: Account<'info, Vault>,
// ... later:
#[account(mut, seeds=[b"vault", user.key().as_ref()], bump = vault.bump)]
pub vault: Account<'info, Vault>,
```

**Common FP** — programs that intentionally derive ad-hoc PDAs for one-shot use (e.g. a nonce account used once and then closed).

### R7 · Uninitialized Account — `uninitialized_account`

**Principle.** `init_if_needed` or `Account::try_from_unchecked` on a freshly-created zero-filled account can be hijacked between creation and first write (same-tx re-init attack).

```rust
// BAD
#[account(init_if_needed, payer=user, space=8+State::LEN)]
pub state: Account<'info, State>,
```

```rust
// GOOD — use plain `init` when idempotence is not required
#[account(init, payer=user, space=8+State::LEN,
          seeds=[b"state", user.key().as_ref()], bump)]
pub state: Account<'info, State>,
// Set a `is_initialized` flag on first write and require!(!state.is_initialized) inside the handler.
```

**Common FP** — `init_if_needed` usages that immediately follow with `require!(!state.already_init())`-style guards. Analyzer traces and drops these.

---

## `solana_ai_analyze` — parameter reference

Invocation signature (Python):

```python
AIAnalyzerTool().run(
    parsed: dict,             # output of solana_parse
    scan_result: dict,        # output of solana_scan
    semgrep_raw: dict,        # output of solana_semgrep
    *,
    provider: str = "openai", # "openai" | "anthropic"
    model: str | None = None, # default: env SOLGUARD_AI_MODEL
    temperature: float = 0.05,
    max_output_tokens: int = 6144,
    token_budget: int = 50_000,
    evidence_max_loc: int = 200,   # per file
    suppression_rules: list[str] = None,   # rule_ids to auto-suppress
    fail_open: bool = True,   # True → DEGRADED report on LLM failure
)
```

Return envelope:

```python
{
    "decision": "proceed" | "review" | "degraded",
    "reason": "str (reason, human-readable)",
    "findings": [ ... merged rule+semgrep+ai findings ... ],
    "usage": {"input_tokens": int, "output_tokens": int, "provider": str, "model": str},
    "elapsed_s": float,
    "notes": list[str],
}
```

Budget accounting halts the loop as soon as `usage.input_tokens + usage.output_tokens >= token_budget`; any unprocessed hints propagate with `confidence=unknown` and the tool returns `decision=degraded`.

---

## CLI & Python API examples

### Skill tool directly (no OpenHarness)

```bash
cd skill/solana-security-audit-skill

# Step 2 — parse
uv run python tools/solana_parse.py \
  --input ../../test-fixtures/real-world/small/rw04_arbitrary_cpi.rs \
  --out   /tmp/sg/parsed.json

# Step 3 — rule scan
uv run python tools/solana_scan.py \
  --parsed /tmp/sg/parsed.json \
  --out    /tmp/sg/scan_result.json

# Step 4 — semgrep (optional — skip if semgrep not installed)
uv run python tools/solana_semgrep.py \
  --input ../../test-fixtures/real-world/small/rw04_arbitrary_cpi.rs \
  --out   /tmp/sg/semgrep.json

# Step 5 — AI analyze (requires OPENAI_API_KEY or ANTHROPIC_API_KEY)
uv run python ai/analyzer_tool.py \
  --parsed   /tmp/sg/parsed.json \
  --scan     /tmp/sg/scan_result.json \
  --semgrep  /tmp/sg/semgrep.json \
  --out      /tmp/sg/verified.json

# Step 6 — emit 3-tier report
uv run python tools/solana_report.py \
  --verified /tmp/sg/verified.json \
  --out-dir  /tmp/sg/out
ls /tmp/sg/out
# → risk_summary.md  assessment.md  checklist.md  report.json
```

### OpenHarness CLI

```bash
# Install once
uv tool install openharness-ai

# Run with a file input
oh run \
  --skill ./skill/solana-security-audit-skill \
  --input-file test-fixtures/real-world/small/rw04_arbitrary_cpi.rs \
  --output-dir ./outputs/manual

# Or with a GitHub URL (backend must pre-normalize the input)
oh run \
  --skill ./skill/solana-security-audit-skill \
  --input-kind github \
  --input-value https://github.com/coral-xyz/sealevel-attacks \
  --output-dir ./outputs/manual
```

### Programmatic Python API

```python
from skill.solana_security_audit_skill.tools import (
    SolanaParseTool, SolanaScanTool, SolanaReportTool,
)
from skill.solana_security_audit_skill.ai import AIAnalyzerTool

parsed = SolanaParseTool().run(root_dir="/path/to/src")
scan   = SolanaScanTool().run(parsed=parsed)
ai     = AIAnalyzerTool().run(parsed=parsed, scan_result=scan, semgrep_raw={"results":[]})
SolanaReportTool().run(verified=ai, out_dir="/tmp/sg/out")
```

---

## References (read on demand — do NOT load upfront)

- [`references/workflow.md`](./references/workflow.md) — granular
  per-step procedure, attacker 10-questions, sibling-function audit,
  Kill-Signal counter-questions.
- [`references/vulnerability-patterns.md`](./references/vulnerability-patterns.md) —
  the 7 Solana rules, each with Bad vs Good code, severity, and
  detection heuristics.
- [`references/report-templates.md`](./references/report-templates.md) —
  three-tier Markdown templates + JSON envelope layout.
- [`references/best-practices.md`](./references/best-practices.md) —
  Solana / Anchor secure-coding guidelines distilled from the Sealevel
  Attacks and Neodyme catalogues.

## Operating rules (summary)

- Treat `work/{task_id}/` as the canonical state directory.
- Record blockers and conflicts explicitly instead of guessing.
- Prefer evidence-backed statements; mark unresolved items as `TODO`
  or `需补件`.
- AI writes narrative prose directly from verified findings; Python
  renders **tables and structural scaffolding only**.
- Steps 2-5 may be skipped for any `normalizedInputs[i]` with
  `kind != "rust_source"` (i.e. `bytecode_only` or `lead_only`); Step 6
  still emits a metadata-only report with an explicit "DEGRADED"
  banner.
