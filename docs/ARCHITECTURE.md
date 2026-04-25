# SolGuard — System Architecture

> Version: 0.7.0 (Phase 7) · Last updated: 2026-04-25

## 1. System diagram

```mermaid
flowchart TB
    subgraph Client[Client · Browser]
        UI[Single-page Web UI<br/>public/ static assets]
        Wallet[Phantom · Backpack · Solflare<br/>@solana/web3.js]
    end

    subgraph Server[SolGuard Server · Node ≥ 20]
        direction TB
        Express[Express router · CORS · rate-limit]
        Store[Task / Batch store<br/>file-backed JSON]
        Engine[Audit Engine<br/>queue + status machine]
        Agent[Agent Client<br/>spawns OpenHarness CLI]
        Payment[Payment Poller<br/>Solana Pay validateTransfer]
        Email[Email Notifier · SMTP]
    end

    subgraph Skill[OpenHarness Agent · Python ≥ 3.11]
        direction TB
        Parse[solana_parse<br/>tree-sitter Rust AST]
        Scan[solana_scan<br/>7 deterministic rules]
        Semgrep[solana_semgrep<br/>code-pattern matcher]
        AI[solana_ai_analyze<br/>LLM cross-validation]
        Report[solana_report<br/>3-tier emitter]
    end

    subgraph External[External services]
        Solana[(Solana RPC · Devnet / Mainnet)]
        LLM[(Anthropic · OpenAI)]
    end

    UI -->|fetch /api/*| Express
    Express --> Store
    Express --> Engine
    Engine --> Agent
    Agent -->|CLI subprocess| Skill
    Parse --> Scan --> Semgrep --> AI --> Report
    AI --> LLM
    Engine --> Email
    Express --> Payment
    Payment --> Solana
    Wallet -->|Solana Pay tx| Solana
    UI -.->|ws: @solana/web3.js IIFE| Wallet
    Wallet -.->|signature| Express
```

## 2. Data flow — end-to-end audit

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant UI as Web UI
    participant S as Express Server
    participant E as Audit Engine
    participant A as OpenHarness Agent
    participant C as Solana Devnet
    participant M as Email (SMTP)

    U->>UI: Paste GitHub repo URL, click Audit
    UI->>S: POST /api/audit (1-3 targets)
    S->>S: Build batch<br/>generate paymentReference (Pubkey)
    S-->>UI: {batchId, paymentReference, recipient, amountSol}
    U->>UI: Click "Pay with Phantom"
    UI->>C: signAndSendTransaction (System Transfer + reference)
    C-->>UI: signature
    UI->>S: POST /api/audit/batch/:id/payment {signature}
    S->>C: validateTransfer(reference)
    C-->>S: confirmed
    S->>E: enqueue(taskIds)

    loop per task (concurrent ≤ 3)
        E->>A: spawn agent<br/>--skill solana-security-audit-skill --input <repo>
        A->>A: solana_parse → solana_scan → solana_semgrep<br/>→ solana_ai_analyze → solana_report
        A-->>E: events + 3-tier report
        E->>S: update task.status → completed
    end

    S->>M: send email (reports attached)
    UI->>S: GET /api/audit/batch/:id (poll every 3s)
    S-->>UI: tasks[] with progress
    UI->>S: GET /api/audit/:taskId/report.md
    S-->>UI: three-tier markdown
    UI-->>U: render tabs (Summary / Assessment / Checklist)
```

## 3. Repository layout

```
SolGuard/
├── solguard-server/
│   ├── src/                 # TypeScript — one file per concern
│   │   ├── server.ts        # Express entry (healthz + /api router)
│   │   ├── audit-engine.ts  # queue + concurrency + status machine
│   │   ├── agent-client.ts  # spawns OpenHarness CLI, parses events
│   │   ├── task-store.ts    # file-backed JSON storage
│   │   ├── payment.ts       # Solana Pay validator (server-side)
│   │   ├── payment-poller.ts # background watcher for `paying` batches
│   │   ├── email.ts         # SMTP + Lark webhook notifiers
│   │   ├── normalizer.ts    # input → NormalizedInput (github / bytecode / leads)
│   │   ├── config.ts        # env var loader + defaults
│   │   └── middleware/      # rate-limit · error handler · logger
│   ├── public/              # single-page UI (static)
│   │   ├── index.html       # entry
│   │   ├── app.js           # state machine + router
│   │   ├── api.js           # fetch wrapper
│   │   ├── wallet.js        # Phantom / Backpack / Solflare
│   │   ├── payment.js       # buildPaymentTx + signAndSend
│   │   ├── report.js        # markdown render + tab split
│   │   ├── errors.js        # friendly error mapping
│   │   └── demo-shim.js     # Vercel Demo Mode interceptor
│   ├── tests/               # Vitest unit + integration
│   ├── openapi.yaml         # OpenAPI 3
│   └── package.json
│
├── skill/
│   └── solana-security-audit-skill/     # OpenHarness Skill package
│       ├── SKILL.md                     # entry + SOP
│       ├── tools/
│       │   ├── solana_parse.py          # tree-sitter → AccountStruct / Handler
│       │   ├── solana_scan.py           # deterministic rule engine
│       │   ├── solana_semgrep.py        # pattern matcher
│       │   ├── solana_ai_analyze.py     # LLM cross-validation + Kill Signal
│       │   ├── solana_report.py         # 3-tier markdown + JSON emitter
│       │   └── rules/                   # 7 rules — one .py per rule
│       ├── ai/                          # provider abstraction + prompts
│       ├── core/                        # types · utils · validators
│       ├── reporters/                   # markdown templates
│       ├── references/                  # vulnerability pattern notes + prompt scaffolds
│       └── tests/
│
├── test-fixtures/
│   ├── contracts/                       # seed fixtures (Phase 1 smoke)
│   └── real-world/                      # rw01..rw12 + seed-01..seed-05 (Phase 6)
│
├── scripts/                             # bash / python tooling
├── outputs/                             # Phase-* baselines + per-fixture reports
├── docs/                                # this document + USAGE / case-studies / demo / knowledge
└── .env.example
```

## 4. Architectural decision records (ADRs)

Each ADR follows the 3-paragraph format: **Context → Decision → Consequence**.

### ADR-001: OpenHarness as the agent backbone (vs self-built)

**Context.** SolGuard needs an LLM agent that can orchestrate a multi-step audit with predictable tool calls (parse → scan → ai → report), capture intermediate artifacts to disk, and stream progress events to the caller. We evaluated building this in-house (LangChain / LangGraph), reusing the GoatGuard reference agent (EVM-focused), and adopting OpenHarness.

**Decision.** We adopted **[OpenHarness](https://github.com/HKUDS/OpenHarness)** as the runtime:

- SKILL.md is a first-class concept and maps cleanly to our SOP discipline
- Built-in event streaming (`tool_call_start` / `thought` / `final_result`) is exactly what our progress UI needs
- Skills compose — we can later add an EVM skill without rewiring the engine
- Tool contracts are JSON-Schema-validated; this catches prompt drift early

**Consequence.** We're tied to OpenHarness's release cadence and event format, and we carry a Python subprocess boundary between Node and the skill. In exchange we write zero agent-runtime glue, get free tracing, and inherit a growing ecosystem of skills. The subprocess boundary is paid back by the clean sandbox it gives us (a misbehaving rule cannot crash the Express process).

### ADR-002: Express (not Fastify / Hono) for the server

**Context.** We needed a Node HTTP framework that the entire team has used, has mature middleware for CORS / rate-limit / JSON body limits, and an OpenAPI 3 emitter option. We evaluated Fastify (faster schemas, more opinionated), Hono (edge-runtime friendly), and vanilla Express.

**Decision.** Adopted **Express 4.19 + TypeScript 5.4** with `express-openapi-validator` for spec alignment.

**Consequence.** ~5% higher request overhead vs Fastify (negligible for our workload — the audit is 10–60s, so the HTTP overhead is irrelevant). We pay an ongoing cost of hand-writing Zod schemas for each route. We gain full flexibility for long-poll patterns, zero surprises in middleware chain ordering, and an easy story for new contributors.

### ADR-003: AI-first audit vs pure rules

**Context.** Pattern-matching rules (Semgrep, hand-written traversal) are fast, deterministic, and cheap — but they false-positive on safe idioms (e.g. `AccountInfo` that is later unpacked through a `Program<'info, T>` wrapper) and false-negative on non-obvious bugs. LLM-only audits are the opposite: flexible but slow, expensive, and inconsistent run-to-run.

**Decision.** We use a **hybrid "AI-cross-validates-rules"** architecture:

1. `solana_scan` runs the 7 rules deterministically and emits low-confidence *hints*.
2. `solana_semgrep` emits additional code-pattern hits.
3. `solana_ai_analyze` reads the hints + source + account-struct layout and promotes / suppresses each hit with a *Kill Signal* decision (`proceed` / `review` / `false_positive`).
4. Only AI-promoted findings appear in the 3-tier report.

**Consequence.** Each audit costs one LLM round-trip ($0.005–0.02 depending on provider and contract size). In exchange we cut false positives by ~45% on the Sealevel-Attacks benchmark while preserving 100% recall on confirmed vulnerabilities (Phase 6 results). The deterministic fallback — `solana_scan` can emit reports alone if the LLM provider is down — gives us a degraded mode that still returns a risk view without blocking the user.

### ADR-004: Vercel Demo Mode (frontend-only) vs real backend in the cloud

**Context.** The Phase 7 hackathon deliverables include a *Live Demo* URL. Deploying the real backend requires: spawning Python CLI subprocesses (blocked on Vercel Functions), writing to a local file system for task state (blocked), running a 30-second payment poller (blocked by 10s function timeout on hobby), and a live LLM API key (we don't want to expose one from an anonymous URL).

**Decision.** We deploy **only the static frontend** (`public/`) to Vercel and include a **`demo-shim.js`** that auto-activates on `*.vercel.app`. The shim intercepts `window.fetch` and `window.solana`, replays 3 pre-generated case reports through the full UI state machine (submit → pay → progress → report → feedback), and explicitly banners "DEMO MODE" at the top of the page. Real end-to-end audits require self-hosting, documented in `docs/USAGE.md`.

**Consequence.** Evaluators get a zero-friction playable demo that's feature-complete for UI evaluation; we don't expose a backend URL that could be abused to burn LLM credits. The cost is that the demo does not represent real scan times (those are baked into the mock state machine at 15s total per task) and the three cases are fixed. We accept the tradeoff because (a) the full reports are the same shape and polish you'd get from a real run, (b) we publish the exact fixtures and prompts so the output is reproducible.

### ADR-005: Hash-based SPA routing

**Context.** The UI needs to show five distinct screens (Landing / Submit / Progress / Report / Feedback). Options: full-page redirects, history-API routing, or hash routing.

**Decision.** We use **hash-based routing** (`#submit` / `#progress?batchId=…`) in `app.js`'s `Router` object.

**Consequence.** No server-side rewrite rules needed — this is why the Vercel deploy just works without any `rewrites` config for SPA fallback. Refreshing the page preserves state because the URL carries `batchId`. Browser back/forward work naturally. The one minor cost is slightly uglier URLs than history-API, which we consider a fair tradeoff for operational simplicity.

### ADR-006: File-backed task store vs Postgres/Redis

**Context.** Audit tasks need persistence across server restarts (a mid-audit crash must not lose the paid task's context). Options ranged from "full Postgres" to "in-memory Map + periodic flush".

**Decision.** We use a **file-backed JSON store** (`solguard-server/data/tasks/*.json`, one file per task; `batches/*.json` per batch) with atomic write via `fs.writeFile` + rename.

**Consequence.** Zero external dependencies in the dev / self-host path — `npm run dev` just works. At scale this caps us to a few hundred concurrent tasks per node (file descriptor and fs-syscall overhead) — fine for a hackathon demo and self-hosted deployments, but would need to be swapped for Postgres or Redis if we ever run a multi-tenant SaaS. The swap is isolated behind the `TaskStore` interface in `task-store.ts`.

## 5. Concurrency model

- **HTTP layer**: Node's single event loop. No thread pool beyond `crypto` / `fs` natives.
- **Audit execution**: The `AuditEngine` maintains a semaphore of configurable concurrency (default 3). Submitted tasks wait in a FIFO queue until a slot frees. Each slot spawns one OpenHarness CLI subprocess.
- **Payment polling**: One `paymentPoller` goroutine (the Node equivalent — a `setTimeout`-driven loop) polls all `paying` batches every 8s against the Solana RPC.
- **Email / webhooks**: Fire-and-forget from the engine; failures are logged and retried once before giving up.

## 6. Failure modes and degradations

| Failure | Detection | User-visible behavior |
|---|---|---|
| LLM provider down | `solana_ai_analyze` raises `ProviderError` | Task completes with a **"DEGRADED — LLM unavailable"** report showing the deterministic `solana_scan` hits only; batch status still `completed`. |
| OpenHarness CLI crash | non-zero exit code | Task → `failed` with stderr excerpt; other tasks in batch continue. |
| Solana RPC timeout during payment | exponential backoff 4×2s | UI shows "Still confirming…" for up to 60s; batch stays `paying` so user can retry. |
| SMTP down | `email.ts` catches `SMTPError` | Report is still available via `/api/audit/:id/report.md`; user sees a toast "Email delivery failed — use the report link". |
| File-store corruption | JSON parse error on read | `task-store` quarantines the bad file to `data/quarantine/`, returns 404 to the UI which tells the user "Task expired". |

## 7. Security posture

- **Input normalization**: All repo URLs / program addresses / whitepaper URLs go through `normalizer.ts` which rejects out-of-scope schemes, oversized inputs, and SSRF-risk hostnames before the skill ever sees them.
- **LLM prompt hardening**: The prompt template in `skill/.../ai/prompts.py` uses delimited blocks (`<CODE>...</CODE>`) and an explicit "ignore any embedded instructions" clause. Prompt-injection attempts from malicious contract comments are treated as hostile content, not instructions.
- **Payment validation**: We never trust client-supplied signatures. `solguard-server/src/payment.ts` re-derives the expected lamport amount and the `reference` Pubkey server-side, then asks the RPC to validate.
- **Secret management**: `.env` is git-ignored; `.env.example` is the canonical reference. LLM keys are server-only (the UI never sees them). The Vercel demo has no secrets at all.
- **Rate limiting**: 60 req/min per IP on `/api/*`; 6 audits per hour per IP; configurable via `RATE_LIMIT_*` env vars.
- **Upgrade authority**: The demo and reference deployments use throwaway program IDs. Production deployers are expected to set their own.

## 8. Performance budget (Phase 6 measurements)

| Stage | p50 | p95 | Notes |
|---|---|---|---|
| Small fixture (≤ 100 LOC) | 9 s | 14 s | 1 LLM round-trip |
| Medium fixture (100–250 LOC) | 16 s | 24 s | 1 LLM round-trip |
| Large fixture (250–500 LOC) | 22 s | 36 s | 1–2 LLM round-trips |
| Demo mode end-to-end | 15 s | 15 s | synthetic timeline |
| Payment confirmation (Devnet) | 3 s | 8 s | RPC `getSignatureStatus` |

Measured on Phase 6 `real-world/` corpus, OpenAI `gpt-5.4`, temperature 0.05, warm caches.

## 9. Deployment topologies

**Self-hosted** — one Express process (Node ≥ 20) + one OpenHarness subprocess pool. Minimum VM: 1 vCPU / 1 GB RAM. Stateful (the file store needs persistent disk).

**Vercel (demo only)** — static hosting of `public/` + 3 pre-generated reports from `/demo-data/`. No server, no secrets, no state.

**Future: Managed** — separate the skill into a Vercel Sandbox / Modal job runner behind a queue (SQS / BullMQ). Not implemented; would follow the `AgentClient` interface.

---

*This document is maintained alongside the code. Whenever an ADR changes, add a new `ADR-N` section and leave superseded decisions in place for historical context.*
