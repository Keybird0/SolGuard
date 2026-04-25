# solguard-server

Express + TypeScript backend for **SolGuard**. Receives audit requests, runs
Solana Pay, dispatches the OpenHarness-based Solana security audit skill (with
a Python fallback), stores results, and emails the final Markdown report to
the user.

> Part of the SolGuard monorepo · [docs/04-SolGuard项目管理/04-Phase3-后端服务开发.md](../../docs/04-SolGuard项目管理/04-Phase3-后端服务开发.md)

## Quick start

```bash
cd SolGuard/solguard-server
cp .env.example .env      # fill ANTHROPIC_API_KEY / SMTP_* / SOLANA_SERVICE_WALLET etc.
npm ci
npm run dev               # http://localhost:3000
```

For local dev without Solana Pay, set `FREE_AUDIT=true` — the server skips
payment and enqueues audits immediately after input normalization.

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Hot-reload dev server (`tsx src/server.ts`) |
| `npm run build` | Compile to `dist/` |
| `npm start` | Run the compiled server |
| `npm run lint` | ESLint + TS rules |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | `node --test` across `src/**/*.test.ts` |
| `bash ../scripts/verify-phase3.sh` | Phase 3 gate (lint + typecheck + test + route smoke) |

## Environment variables

See [.env.example](./.env.example) for the complete list. Highlights:

| Var | Default | Purpose |
|---|---|---|
| `PORT` | 3000 | HTTP port |
| `FREE_AUDIT` | false | Skip Solana Pay (dev only) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | — | LLM providers (at least one required) |
| `SOLANA_CLUSTER` / `SOLANA_RPC_URL` / `SOLANA_SERVICE_WALLET` | devnet / … | Payment recipient |
| `AUDIT_PRICE_SOL` | 0.001 | Price per audit |
| `OH_CLI_PATH` | `oh` | OpenHarness CLI binary |
| `OH_SKILL_DIR` | — | Path to `solana-security-audit-skill` |
| `RUNNER_FALLBACK_TO_PYTHON` | true | If `oh` is missing / fails, run `run_audit.py` via subprocess |
| `PYTHON_BIN` / `PYTHON_RUN_AUDIT_SCRIPT` | uv / …`run_audit.py` | Fallback runner |
| `GIT_BIN` / `INPUT_NORMALIZER_TIMEOUT_MS` | git / 120000 | Git clone for `github` inputs |
| `AGENT_CALLBACK_TOKEN` | change-me | Shared secret for `POST /api/audit/:id/complete` |
| `AGENT_HMAC_REQUIRED` | false (true in prod) | Require HMAC-SHA256 signature header |
| `RATE_LIMIT_ENABLED` / `_WINDOW_MS` / `_MAX_REQUESTS` | false / 60_000 / 10 | Sliding-window rate limit |
| `SMTP_*` | — | Email delivery (omit to log-only) |
| `TASK_STORE` | in-memory | or `file-json` |

## API

All endpoints mounted under `/api` (except health/static). A machine-readable
description is in [openapi.yaml](./openapi.yaml).

### `POST /api/audit`
Create a new audit task.

Body:
```json
{
  "inputs": [
    { "type": "github",           "value": "https://github.com/owner/repo" },
    { "type": "contract_address", "value": "<base58 Solana address>" },
    { "type": "whitepaper",       "value": "https://…/paper.pdf" },
    { "type": "website",          "value": "https://…" }
  ],
  "email": "user@example.com"
}
```

Response (FREE_AUDIT=true):
```json
{ "taskId": "<uuid>", "status": "paid", "freeAudit": true }
```

Response (payment required):
```json
{
  "taskId": "<uuid>",
  "status": "paying",
  "paymentUrl": "solana:<recipient>?amount=0.001&reference=…",
  "paymentReference": "<base58>",
  "recipient": "<base58>",
  "amountSol": 0.001,
  "cluster": "devnet",
  "expiresAt": "2026-04-22T…"
}
```

### `GET /api/audit/:taskId`
Returns the full task record (sans `reportMarkdown` unless completed).

### `POST /api/audit/:taskId/payment`
Client-pushed payment signature. Verifies on-chain; on success flips status to
`paid` and enqueues the audit pipeline. Avoids waiting for the 5s poller.

### `POST /api/audit/:taskId/complete`
Internal callback from the agent runner. Auth: either
* `X-Agent-Signature: sha256=<hex>` over the raw body (HMAC-SHA256 keyed by
  `AGENT_CALLBACK_TOKEN`), **or**
* `X-Agent-Token: <token>` (legacy; rejected in production when
  `AGENT_HMAC_REQUIRED=true`).

Body: `{ status, findings, statistics, reportMarkdown, reportUrl?, error? }`.

### `GET /api/audit/:taskId/report.md`
Markdown download; `text/markdown` + `Content-Disposition: attachment`.

### `GET /api/audit/:taskId/report.json`
Public JSON snapshot (no email / signatures).

### `POST /api/feedback`
`{ taskId?, email?, rating: 1-5, content? }` — appended to `data/feedback.jsonl`
and optionally forwarded to `FEEDBACK_WEBHOOK_URL`.

### `GET /healthz` / `GET /readyz`
Standard health probes.

## Dual-path audit runner

Two code paths exist for running the skill; `audit-engine.ts` picks one:

1. **Default — `oh -p` (agentic)**: spawns the OpenHarness CLI with the prompt
   in `buildAuditPrompt()`; events stream back as JSON and get mapped to
   `AgentEvent`.
2. **Fallback — `run_audit.py` (Python subprocess)**: direct invocation of the
   pipeline script in `../skill/solana-security-audit-skill/scripts/run_audit.py`,
   fed the same `normalizedInputs` array and a callback URL. Triggered when
   `RUNNER_FALLBACK_TO_PYTHON=true` and either `oh` is missing, `FREE_AUDIT=true`,
   or the CLI path repeatedly fails. See [src/runners/python-runner.ts](./src/runners/python-runner.ts).

## Input normalization

Any `AuditInput` is normalized by [src/input-normalizer/](./src/input-normalizer/)
before the audit runs:

| Input type | Produces | Path |
|---|---|---|
| `github` | `rust_source { rootDir, primaryFile }` | `git clone --depth=1` + BFS for `programs/*/src/lib.rs` |
| `contract_address` | `bytecode_only { programId, bytecodePath }` | `connection.getAccountInfo()` → `.so` |
| `whitepaper` / `website` | `lead_only` OR recurse | `fetch` + HTML strip + LLM/regex lead extraction (GitHub URL / Solana address) |

Failures per-input are non-fatal (recorded in `task.normalizeError`); all
inputs failing sets the task to `failed`.

## Layout

```
src/
  server.ts                 Express app bootstrap
  config.ts                 Zod-validated env
  types.ts                  Domain types (AuditTask, NormalizedInput, Finding, …)
  routes/                   audit.ts / feedback.ts / health.ts
  validators/               Zod body schemas
  payment.ts                Solana Pay helpers
  payment-poller.ts         Background poller: paying → paid
  openharness-client.ts     `oh -p` spawn + JSON-stream parse
  audit-engine.ts           Task orchestrator (runs either runner, updates store)
  runners/python-runner.ts  Python subprocess runner (fallback path)
  input-normalizer/         github | contract_address | url (whitepaper/website)
  middleware/               error-handler.ts, rate-limit.ts
  storage/                  in-memory + file-json task stores
  email.ts                  SMTP mailer (nodemailer)
```
