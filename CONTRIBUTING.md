# Contributing to SolGuard

> Thanks for your interest in SolGuard. This document gets you from a clean
> clone to a working dev loop, explains coding conventions, and shows step-by-step
> how to add a new scanner rule (the most common contribution).
>
> 中文阅读者：本文档只维护英文版，术语表在底部。大多数流程指令可直接复制使用。

## Table of contents

- [1. Quick dev setup (10 minutes)](#1-quick-dev-setup-10-minutes)
- [2. Repository tour](#2-repository-tour)
- [3. Coding conventions](#3-coding-conventions)
- [4. Pull-request workflow](#4-pull-request-workflow)
- [5. Adding a new Solana scanner rule — step by step](#5-adding-a-new-solana-scanner-rule--step-by-step)
- [6. Testing your change](#6-testing-your-change)
- [7. Reporting bugs / security issues](#7-reporting-bugs--security-issues)
- [8. Glossary 术语表](#8-glossary-术语表)

---

## 1. Quick dev setup (10 minutes)

### Prerequisites

| Tool | Minimum version | Purpose |
|---|---|---|
| [`uv`](https://github.com/astral-sh/uv) | 0.4+ | Python env + deps |
| Python | 3.11 | Skill / OH agent runtime |
| Node.js | 20 LTS | Express server + frontend |
| Anchor CLI | 0.30 | Building test fixtures (optional) |
| Solana CLI | 1.18 | Devnet interaction (optional) |

### Clone + install

```bash
git clone https://github.com/Keybird0/SolGuard.git
cd SolGuard

# Python (skill + OH agent)
uv sync --all-extras

# Node (server + frontend static assets)
cd solguard-server && npm install && cd ..
```

### First run (smoke test)

```bash
# Run the skill directly on a fixture
cd skill/solana-security-audit-skill
uv run python tools/solana_parse.py \
  --input ../../test-fixtures/real-world/small/rw04_arbitrary_cpi.rs \
  --out   /tmp/sg/parsed.json
uv run python tools/solana_scan.py \
  --parsed /tmp/sg/parsed.json \
  --out    /tmp/sg/scan.json
uv run python tools/solana_report.py \
  --verified /tmp/sg/scan.json \
  --out-dir  /tmp/sg/out
ls /tmp/sg/out
# → risk_summary.md  assessment.md  checklist.md  report.json

# Or start the full stack (needs OPENAI_API_KEY)
cd solguard-server
cp .env.example .env   # fill in OPENAI_API_KEY, MAIL_PROVIDER etc.
npm run dev            # http://localhost:3000
```

### Optional: Demo Mode locally

```bash
cd solguard-server
npx http-server public -p 8080
open 'http://localhost:8080/?demo=1'    # demo-shim.js kicks in
```

---

## 2. Repository tour

```
SolGuard/
├── skill/                    ← OpenHarness-compatible Skill (Python)
│   └── solana-security-audit-skill/
│       ├── SKILL.md          ← Skill descriptor (Anthropic agent skill spec)
│       ├── tools/
│       │   ├── solana_parse.py   → Step 2: AST / struct extraction
│       │   ├── solana_scan.py    → Step 4: 7 rule checks
│       │   ├── solana_semgrep.py → Step 4b: Semgrep rules (optional)
│       │   └── solana_report.py  → Step 6: emit 3-tier reports
│       ├── ai/
│       │   └── analyzer_tool.py  → Step 5: LLM deep-review
│       └── rules/semgrep-*.yaml  → 7 Semgrep rulesets
├── solguard-server/          ← Express.js backend + frontend static files
│   ├── src/                      → Express routes / payment / storage
│   ├── public/                   → SPA (vanilla JS + demo-shim)
│   ├── openapi.yaml              → API spec (v0.7.0)
│   └── vercel.json               → Static-only hosting config
├── tools/                    ← Harness CLI (Phase 2 baseline runner)
├── test-fixtures/            ← 14 Anchor/Native programs (small / medium / large)
├── outputs/                  ← Generated audit artifacts (git-ignored)
├── docs/                     ← Architecture, usage, case studies, demo
│   ├── ARCHITECTURE.md
│   ├── USAGE.md  +  USAGE.zh-CN.md
│   ├── case-studies/             → 3 reference audits (for Demo Mode)
│   ├── demo/                     → script.md, deck-source.md
│   └── knowledge/solana-vulnerabilities.md   → Developer-facing 7-rule doc
├── LICENSE + LICENSE-THIRD-PARTY.md
└── README.md + README.zh-CN.md
```

Parts you are likely to touch as a contributor:

- **New rule** → `skill/.../tools/solana_scan.py` + `rules/semgrep-*.yaml` + `skill/.../references/vulnerability-patterns.md` + `docs/knowledge/solana-vulnerabilities.md`.
- **Frontend / demo** → `solguard-server/public/`.
- **API** → `solguard-server/src/routes/` + `openapi.yaml`.
- **Docs** → `docs/` and both `README.md` files.

---

## 3. Coding conventions

### Python (skill + harness)

- **Formatter**: `ruff format` (run via `uv run ruff format .`).
- **Linter**: `ruff check .` — all rules in `pyproject.toml` are enforced.
- **Type-checker**: `mypy skill/solana-security-audit-skill`.
- **Style**:
  - Each `check_<rule_id>` function must be **pure**: takes `parsed: ParsedContract`,
    returns `list[dict[str, Any]]`, no I/O, no globals.
  - Dataclasses over dicts for rich types; dicts on the boundary (JSON IO).
  - `assert` only in tests; use `raise ValueError` in prod code.

### TypeScript / JavaScript (server + frontend)

- **Formatter**: Prettier (config in `solguard-server/.prettierrc`).
- **Linter**: ESLint (`eslint.config.mjs`).
- Frontend is plain ES modules; no bundler. Keep new modules `.js` in
  `public/` and import them with `<script type="module">`.

### Rust (test fixtures)

- Fixtures follow `anchor-lang = "0.30"` or raw `solana-program = "1.18"`.
- **Do not** change the name of the root library / program id — the parser
  keys off those.

### Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <summary>

[optional body]

[optional footer]
```

Valid `type`s: `feat` | `fix` | `perf` | `docs` | `refactor` | `test` |
`build` | `ci` | `chore`.

Valid `scope`s: `skill` | `server` | `frontend` | `harness` | `docs` |
`demo` | `fixtures` | `ci`.

Examples:

- `feat(skill): add close_instruction rule (R8)`
- `fix(server): handle empty batch pollers cleanly`
- `docs(usage): add Phantom Devnet switch guide`

---

## 4. Pull-request workflow

1. **Fork** + **branch** from `main`. Branch name: `feat/<short-topic>` or
   `fix/<issue-number>-<slug>`.
2. **Keep the PR small**: < 500 LoC diff is ideal. Split refactors and
   feature additions.
3. **Update docs in the same PR** when touching public-facing behaviour
   (API contract, rule catalogue, CLI flags).
4. **Run the full test suite** locally before pushing (see §6).
5. **Fill the PR template**: motivation · approach · testing plan · linked
   issue.
6. **CI must be green** before review. If CI flakes, retry once; if it
   repeats, file an issue instead of merging around it.
7. **At least one approver** for non-docs changes. Docs-only PRs can be
   self-merged by maintainers after CI.
8. **Squash-merge** into `main`. Delete the branch after merge.

---

## 5. Adding a new Solana scanner rule — step by step

This is the most common contribution. Below is a complete checklist walking
you from idea to merged PR, using **R4 Arbitrary CPI** as a reference.

### Step 0. Check prior art

- Is it already in `skill/.../references/vulnerability-patterns.md`?
- Is there a Sealevel Attacks lesson covering it? If yes, link it in the PR.
- Does Semgrep have an existing rule? If yes, start from `rules/semgrep-*.yaml`.

### Step 1. Write a test fixture

Create `test-fixtures/custom/<your_rule>.rs`:

```rust
// BAD — should trigger your new rule
pub fn bad_handler(ctx: Context<BadAccounts>) -> Result<()> { ... }

// GOOD — should NOT trigger (kill signal)
pub fn good_handler(ctx: Context<GoodAccounts>) -> Result<()> { ... }
```

Include **both** a positive and a negative case in the same file — the
harness will exercise both.

### Step 2. Add a pure function in `solana_scan.py`

`skill/solana-security-audit-skill/tools/solana_scan.py` currently has **7
pure functions**. Add an 8th right after `check_uninitialized_account`:

```python
def check_close_instruction_missing(parsed: ParsedContract) -> list[dict[str, Any]]:
    """R8: close handler doesn't zero account data or discriminator."""
    findings: list[dict[str, Any]] = []
    for handler in parsed.handlers:
        if not handler.name.startswith("close_"):
            continue
        body = handler.body_source or ""
        has_zero = "data.fill(0)" in body or "#[account(close =" in handler.attrs
        has_lamports_zero = "= 0" in body and "lamports" in body
        if has_lamports_zero and not has_zero:
            findings.append({
                "rule_id": "close_instruction_missing",
                "severity": "High",
                "title": f"Close handler {handler.name} leaves data intact",
                "description": ...,
                "evidence": {"file": handler.file, "lines": [handler.start_line, handler.end_line]},
                "recommendation": ...,
                "confidence": "medium",
            })
    return findings
```

Requirements:

1. **Pure**: no I/O, no mutation of inputs, deterministic given the same
   `parsed`.
2. **Returns a list of finding dicts** matching the schema in
   `skill/.../references/report-templates.md` § "Finding schema".
3. **No exceptions escape**: catch and record into `finding.evidence.errors`
   if parsing goes wrong.

Register it in the dispatcher at the bottom of `solana_scan.py`:

```python
RULE_CHECKERS: list[tuple[str, Callable[[ParsedContract], list[dict]]]] = [
    ...
    ("close_instruction_missing", check_close_instruction_missing),
]
```

### Step 3. (Optional) Mirror in Semgrep

Create `skill/.../rules/semgrep-close_instruction_missing.yaml` using the
schema in `rules/semgrep-arbitrary_cpi.yaml` as the template.

### Step 4. Extend `vulnerability-patterns.md` + `docs/knowledge/solana-vulnerabilities.md`

- Add a new `## N. Close Instruction · close_instruction_missing · High`
  section to `skill/.../references/vulnerability-patterns.md` (tool-side
  prompt attachment).
- Mirror with ≥ 100 lines of developer-facing content in
  `docs/knowledge/solana-vulnerabilities.md`.
- Update the quick-reference tables in both files.

### Step 5. Extend AI prompt (if the rule needs LLM verification)

Edit `skill/.../ai/analyzer_tool.py`:

- Add the new rule id to `SUPPRESSION_RULES` if there is a common false
  positive.
- Add a few-shot example to the prompt builder (`_build_prompt_v2`).

### Step 6. Write unit tests

- `skill/solana-security-audit-skill/tests/test_solana_scan.py` — add test
  cases for your new function.
- `tests/test_harness.py` — add a row to the fixture table so the baseline
  harness runs against your fixture.

### Step 7. Update the SKILL.md rule card

Append your rule to `skill/.../SKILL.md` § "Rule Reference Card" — Principle,
Bad, Good, Common FP.

### Step 8. Re-run the baseline

```bash
uv run python tools/harness_run.py \
  --fixtures test-fixtures/custom/<your_rule>.rs \
  --output-dir outputs/custom-$(date +%Y%m%d)
```

Confirm:

- Your BAD handler produces a finding with correct rule_id + severity.
- Your GOOD handler produces **no** finding (or an Info-level one you can
  justify).

### Step 9. Open the PR

- Title: `feat(skill): add R8 close_instruction_missing rule`.
- Body checklist:
  - [ ] New pure function in `solana_scan.py`.
  - [ ] Semgrep rule (or "n/a — pure AST check").
  - [ ] Docs updated in `vulnerability-patterns.md` + `solana-vulnerabilities.md`.
  - [ ] `SKILL.md` rule card updated.
  - [ ] Unit tests pass.
  - [ ] Fixture added + baseline re-run attached.

---

## 6. Testing your change

### Python

```bash
uv run pytest skill/solana-security-audit-skill/tests -v
uv run pytest tests -v
```

### TypeScript / frontend

```bash
cd solguard-server
npm run test
npm run lint
```

### Harness baseline (full regression)

```bash
uv run python tools/harness_run.py \
  --suite baseline \
  --output-dir outputs/ci-$(date +%Y%m%d-%H%M)
```

Pass criteria: baseline against `outputs/phase6-baseline/` should not
regress (existing HIGH findings remain, no new false positives above the
accepted threshold in `docs/phase3-evaluation-plan.md`).

---

## 7. Reporting bugs / security issues

### Regular bugs

Open a GitHub issue with:

- Reproducer (minimal fixture or curl invocation)
- Expected vs actual behaviour
- Logs (sanitize RPC URLs / API keys)

### Security issues

**Do not open a public issue.** Instead email `security@example.org` (or
whichever address the current maintainer publishes). We aim to respond
within 72 hours. Coordinated disclosure timeline: 90 days default, shorter
if actively exploited.

---

## 8. Glossary 术语表

| EN | 中文 | Meaning |
|---|---|---|
| Rule / checker | 检测规则 | A pure function in `solana_scan.py` that emits findings |
| Finding | 发现 / 漏洞 | A single issue reported by a rule, with file/lines/severity |
| Severity | 严重度 | `Critical > High > Medium > Low > Info` |
| Kill signal | 误报排除信号 | A code pattern that suppresses a rule hit (reduces FP) |
| CPI | 跨程序调用 | `invoke` / `invoke_signed` — Solana's equivalent of `call` |
| PDA | 程序派生地址 | Program-Derived Address |
| Discriminator | 类型判别符 | Anchor's 8-byte prefix identifying account type |
| Signer | 签名者 | An `AccountInfo` where `is_signer == true` |
| DEGRADED mode | 降级模式 | Report produced when LLM verification fails (rules-only) |

Welcome aboard — happy auditing. 🛡️
