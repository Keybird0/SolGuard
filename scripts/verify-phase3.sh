#!/usr/bin/env bash
# =====================================================
# SolGuard · Phase 3 Verification Script (Backend Gate)
#
# Runs the acceptance checks listed in
#   docs/04-SolGuard项目管理/04-Phase3-后端服务开发.md
#
# Exit code 0 ⇒ Phase 3 passes; non-zero ⇒ failure count.
# =====================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$ROOT/solguard-server"
cd "$SERVER_DIR"

PASS=0
FAIL=0
WARN=0

color()  { printf "\033[%sm%s\033[0m" "$1" "$2"; }
green()  { color "32" "$1"; }
red()    { color "31" "$1"; }
yellow() { color "33" "$1"; }
bold()   { color "1"  "$1"; }

pass() { echo "  $(green "✓") $1"; PASS=$((PASS+1)); }
fail() { echo "  $(red   "✗") $1"; FAIL=$((FAIL+1)); }
warn() { echo "  $(yellow "!") $1"; WARN=$((WARN+1)); }
sect() { echo; echo "$(bold "$1")"; }

sect "P3.1 Project baseline"
[ -f package.json ] && pass "package.json present" || fail "package.json missing"
[ -f tsconfig.json ] && pass "tsconfig.json present" || fail "tsconfig.json missing"
[ -f .eslintrc.json ] && pass ".eslintrc.json present" || fail ".eslintrc.json missing"
[ -f .env.example ] && pass ".env.example present" || fail ".env.example missing"

sect "P3.1 / P3.2 / P3.3 / P3.4 / P3.5 / P3.6 Source modules"
for f in \
  src/server.ts \
  src/config.ts \
  src/logger.ts \
  src/types.ts \
  src/routes/audit.ts \
  src/routes/health.ts \
  src/routes/feedback.ts \
  src/storage/task-store.ts \
  src/storage/file-json-task-store.ts \
  src/middleware/error-handler.ts \
  src/validators/audit.ts \
  src/payment.ts \
  src/payment-poller.ts \
  src/openharness-client.ts \
  src/audit-engine.ts \
  src/email.ts
do
  [ -f "$f" ] && pass "$f" || fail "$f missing"
done

sect "P3.* Newly added modules (Phase 3)"
for f in \
  src/runners/python-runner.ts \
  src/runners/python-runner.test.ts \
  src/input-normalizer/index.ts \
  src/input-normalizer/normalize-github.ts \
  src/input-normalizer/normalize-contract-address.ts \
  src/input-normalizer/normalize-url.ts \
  src/middleware/rate-limit.ts \
  src/middleware/rate-limit.test.ts
do
  [ -f "$f" ] && pass "$f" || fail "$f missing"
done

sect "P3.* Build + Lint + Typecheck"
if npm run --silent typecheck >/tmp/solguard-typecheck.log 2>&1; then
  pass "npm run typecheck clean"
else
  fail "typecheck errors (see /tmp/solguard-typecheck.log)"
fi
if npm run --silent build >/tmp/solguard-build.log 2>&1; then
  pass "npm run build succeeds"
else
  fail "build failed (see /tmp/solguard-build.log)"
fi
if npm run --silent lint >/tmp/solguard-lint.log 2>&1; then
  pass "npm run lint clean"
else
  fail "lint errors (see /tmp/solguard-lint.log)"
fi

sect "P3.Final Unit + integration tests"
if npm test >/tmp/solguard-test.log 2>&1; then
  pass "npm test: all pass"
  grep -E "^ℹ (tests|pass|fail)" /tmp/solguard-test.log | sed 's/^/      /'
else
  fail "tests failed (see /tmp/solguard-test.log)"
fi

sect "P3.1.3 / P3.* Route smoke (FREE_AUDIT mode)"
if command -v curl >/dev/null; then
  PORT=31337
  PORT=$PORT FREE_AUDIT=true NODE_ENV=test LOG_LEVEL=error TASK_STORE=in-memory \
    AGENT_CALLBACK_TOKEN=smoke-token \
    npx tsx src/server.ts >/tmp/solguard-smoke.log 2>&1 &
  PID=$!
  sleep 3
  BASE="http://127.0.0.1:$PORT"

  if curl -fsS "$BASE/healthz" >/tmp/solguard-healthz.json 2>&1; then
    pass "GET /healthz 200"
  else
    warn "healthz smoke failed (see /tmp/solguard-smoke.log)"
  fi

  # POST /api/audit returns a task id in FREE_AUDIT mode. Use a deliberately
  # non-existent repo so the normalizer fails fast and the backend stays
  # responsive — we only care that the HTTP contract is honored here.
  CREATE_BODY='{"inputs":[{"type":"github","value":"https://github.com/solguard-smoke/does-not-exist"}],"email":"smoke@example.com"}'
  CREATE_RESP=$(curl -fsS -X POST "$BASE/api/audit" -H 'Content-Type: application/json' -d "$CREATE_BODY" || true)
  if echo "$CREATE_RESP" | grep -q '"taskId"'; then
    pass "POST /api/audit 201 (FREE_AUDIT)"
    TASK_ID=$(echo "$CREATE_RESP" | sed -nE 's/.*"taskId":"([^"]+)".*/\1/p')
    # The task is now in state "paid"; hit status endpoint
    if curl -fsS "$BASE/api/audit/$TASK_ID" >/tmp/solguard-task.json 2>&1; then
      pass "GET /api/audit/:id 200"
    else
      fail "GET /api/audit/:id failed"
    fi
    # Unknown task: 404
    if curl -o /dev/null -s -w '%{http_code}' "$BASE/api/audit/not-a-task/report.md" | grep -q '^404$'; then
      pass "GET /api/audit/:id/report.md 404 for unknown"
    else
      fail "report.md unknown-task expected 404"
    fi
    if curl -o /dev/null -s -w '%{http_code}' "$BASE/api/audit/not-a-task/report.json" | grep -q '^404$'; then
      pass "GET /api/audit/:id/report.json 404 for unknown"
    else
      fail "report.json unknown-task expected 404"
    fi
    # payment push on FREE_AUDIT (status=paid) → 409 INVALID_STATE
    PAY_CODE=$(curl -o /dev/null -s -w '%{http_code}' -X POST "$BASE/api/audit/$TASK_ID/payment" \
      -H 'Content-Type: application/json' -d '{"signature":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}' || true)
    if [ "$PAY_CODE" = "409" ]; then
      pass "POST /api/audit/:id/payment 409 when status=paid"
    else
      fail "expected 409 from payment push, got $PAY_CODE"
    fi
  else
    fail "POST /api/audit did not return a taskId (resp: $CREATE_RESP)"
  fi

  kill $PID >/dev/null 2>&1 || true
  wait $PID 2>/dev/null || true
else
  warn "curl not found; skipping smoke"
fi

sect "P3.* Skill tool manifest smoke (Phase 2 tool contract)"
SKILL_SMOKE="$ROOT/skill/solana-security-audit-skill/scripts/oh_skill_smoke.sh"
if [ -x "$SKILL_SMOKE" ]; then
  if bash "$SKILL_SMOKE" >/tmp/solguard-skill-smoke.log 2>&1; then
    pass "oh_skill_smoke.sh succeeds"
  else
    warn "oh_skill_smoke.sh failed (see /tmp/solguard-skill-smoke.log)"
  fi
else
  warn "oh_skill_smoke.sh not found / not executable"
fi

sect "Summary"
echo "  $(green "pass: $PASS")  $(red "fail: $FAIL")  $(yellow "warn: $WARN")"

if [ "$FAIL" -gt 0 ]; then
  echo; echo "$(red "Phase 3 gate NOT passed")"; exit "$FAIL"
else
  echo; echo "$(green "Phase 3 gate PASSED")"; exit 0
fi
