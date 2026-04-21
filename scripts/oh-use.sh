#!/usr/bin/env bash
# scripts/oh-use.sh — 在 OpenHarness CLI 的 profile 之间做无交互切换
#
# Why: `oh setup <profile>` 是交互式的，在 agent shell / CI 里用不了；
#      直接改 ~/.openharness/settings.json 可一行命令切换 + 冒烟。
#
# 用法:
#   bash scripts/oh-use.sh                       # 打印当前 profile 与候选
#   bash scripts/oh-use.sh copilot               # 切到 Copilot (model=sonnet)
#   bash scripts/oh-use.sh openai-compatible     # 切到 openai-compatible (读取 profile 内的 default_model / base_url)
#   bash scripts/oh-use.sh claude-api            # 切到 Anthropic
#
# 约束:
#   - 本脚本 **不会** 写入任何 API Key；Key 必须提前通过 P1.1.2 的一次性注入脚本写入 settings.json
#   - 切换完成后自动跑 `oh -p "Reply only: OK"` 冒烟（10s timeout via Python）
#
# 与风险登记册的关系:
#   - R15: 若模型别名失效 → 手动编辑 settings.json 下的 default_model/last_model
#   - R16: 若切到 openai-compatible 后上游 502 → 见 10-风险登记册与应急预案 §R16 Plan A/B/C

set -euo pipefail

SETTINGS="${HOME}/.openharness/settings.json"

if [[ ! -f "${SETTINGS}" ]]; then
  echo "❌ ${SETTINGS} 不存在 — 请先执行 P1.1.1 (oh setup) 或 P1.1.2 §执行记录 的注入脚本"
  exit 1
fi

TARGET="${1:-}"

if [[ -z "${TARGET}" ]]; then
  python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".openharness/settings.json"
d = json.loads(p.read_text())
print("active_profile :", d.get("active_profile"))
print("model          :", d.get("model"))
print("base_url       :", d.get("base_url"))
print("api_format     :", d.get("api_format"))
print("candidates     :", list(d.get("profiles", {}).keys()))
PY
  exit 0
fi

python3 - "$TARGET" <<'PY'
import json, pathlib, sys

target = sys.argv[1]
p = pathlib.Path.home() / ".openharness/settings.json"
d = json.loads(p.read_text())

if target not in d.get("profiles", {}):
    print(f"❌ unknown profile: {target}")
    print("   candidates:", list(d.get("profiles", {}).keys()))
    sys.exit(2)

prof = d["profiles"][target]

d["active_profile"] = target
d["provider"]       = prof.get("provider", "")
d["api_format"]     = prof.get("api_format", "")
d["model"]          = prof.get("default_model") or prof.get("last_model") or d.get("model")
d["base_url"]       = prof.get("base_url")
d["context_window_tokens"]         = prof.get("context_window_tokens") or d.get("context_window_tokens")
d["auto_compact_threshold_tokens"] = prof.get("auto_compact_threshold_tokens") or d.get("auto_compact_threshold_tokens")

p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")

print(f"✅ switched: active_profile={target} model={d['model']} base_url={d['base_url']} api_format={d['api_format']}")
PY

echo "--- smoke: oh -p 'Reply only: OK' ---"
if OUT="$(oh -p 'Reply only: OK' 2>&1)"; then
  echo "${OUT}" | tail -3
  if echo "${OUT}" | grep -q "502\|forbidden\|model_not_supported"; then
    cat <<EOF

⚠️  上游或模型异常 — 参考:
   - R15 (model_not_supported): 改 ~/.openharness/settings.json 里的 default_model/last_model
   - R16 (502 Upstream forbidden): 上游 UA 白名单问题，见 docs/04-SolGuard项目管理/10-风险登记册与应急预案.md §R16

EOF
    exit 3
  fi
else
  echo "❌ oh invocation failed"
  exit 4
fi
