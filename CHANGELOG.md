# Changelog

All notable changes to SolGuard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Phase 7C · 04-实现预期对齐（v0.8.1）**（2026-04-26）：按 `docs/03-现有材料与项目规划/04-实现预期.md` 全文逐条对照（A 6 / B 7 / C 6 项），补齐 3 条真实差距（B1 + B7-ii + C4-ii），剔除 2 条"现状优于预期"的伪差距（B2 + B3，决定不回退到 LLM 编排），并把"不能立刻落地的 4 条"明确归到 M2/M3 路线图。
  - **B7-ii · 链上 authority 数据接通**（最大杠杆，`AuthorityInfo` schema 既存但**未通电**的死字闭环）：扩 `solguard-server/src/input-normalizer/normalize-contract-address.ts`：`getAccountInfo` 后按 owner 分流——SPL Token / Token-2022 → 解析 82 字节 Mint layout 拉 `mint_authority` + `freeze_authority`（COption 标志 + 32 字节 pubkey）；Token-2022 → 继续 walk TLV 抽取扩展（`PermanentDelegate` / `TransferHook` / `TransferFee` 等共 23 类已知 + `unknown_<num>` fallback）；BPFLoaderUpgradeable → 解析 Program 枚举 (tag=2) 取 `programdata_address`，**链式第二次 RPC** 取 ProgramData header (tag=3 + slot + COption) 抽 `upgrade_authority`；BPFLoader2/legacy → 直接判 `program-finalised` (immutable)。新建 `OnchainAuthority` interface in `src/types.ts`；`NormalizedInput.bytecode_only.onchain` 新增可选字段。`audit-engine.ts::formatNormalizedInputs` 把 `mint_authority/freeze_authority/upgrade_authority/token2022_extensions/parse_note` 拼到 prompt 的"## 后端预规整结果"段，并在 prompt DEGRADED 路径加 v0.8.1 链上数据使用约定（"即便 LLM 不可用，链上数据小节也必须输出"）。`references/report-templates.md` 顶部新增 §"v0.8.1 链上数据源"，给出 prompt 字段 → Risk Summary / Assessment §6/§7 / Checklist 11/12/14 的字段映射 + Token-2022 红旗扩展白名单。**测试 +3 例**（normalize-contract-address.test.ts 新增 168 行，使用 `@solana/web3.js` PublicKey 构造合法 Mint / Token-2022 + 1 PermanentDelegate / 上游 Program + 下游 ProgramData 双 RPC 链路），全部通过；`npx tsc --noEmit` 零错。
  - **B1 + C4-ii · 双轨恶意输入守门**：新增 `solguard-server/src/validators/more-info-guard.ts`（**轨道 A**，~150 行，零 LLM）—— 6 条启发式规则，按特异度排序：`INJECTION_PHRASE`（17 条黑名单短语）→ `ENVELOPE_BREAKER`（13 条 prompt-envelope 越狱 token）→ `OVERLONG_LINE`（单行 ≥500 char）→ `LONG_BASE64_BLOCK`（≥200 字节 base64 字符块）→ `DISALLOWED_URL_SCHEME`（仅 http/https/mailto 白名单）→ `CONTROL_CHARS`（ANSI/null）；first-match-wins，`reason` 永不回显原文（防反射攻击）；`validateMoreInfo()` 注入 `validators/audit.ts` 两处 Zod `superRefine`（`auditInputSchema`-legacy + `targetSchema`-P4.6 双轨），错误带 `params.code='MALICIOUS_INPUT' + ruleId`。**测试 +11 例**（`more-info-guard.test.ts` 5 通过 + 5 拒绝 + 1 边缘；`validators/audit.test.ts` +1 例验证 Zod 集成）；既有"rejects moreInfo > 2000 chars"测试改写为多行 string 避免误踩 OVERLONG_LINE 启发式。新增 `skill/.../references/input-guard-prompt.md`（**轨道 B**，~210 行，asset-ready / default off）—— system prompt 给 4 字段 JSON schema（`verdict/category/confidence/evidence`，无 prose / 无 markdown fence）+ user prompt 模板 + Haiku 4.5 调用参数 + 启发式 × LLM 兜底动作表 + fail-open 政策；通过 `INPUT_GUARD_LLM_FALLBACK=true` env 启用，satisfies C4-ii 的 prompt 资产准备预期。
  - **ADR-009 · Deterministic input classification & normalization**（`docs/ARCHITECTURE.md`）：新增一节解释为什么 B2/B3 不让 AI 编排——v0.8 skill-first 的明确边界（IO + 错误处理 + 格式检测 → 确定性；规则歧义 + 攻击场景推演 → AI），引用 ADR-007 作为"砍 1100 LoC Python LLM 硬编码"的精神延续。同时新增 §"Prompt Asset Inventory"，把 C4-i/ii/iii/iv 4 条预期映射到 SKILL.md / input-guard-prompt.md / l3-agents-playbook.md / l4-judge-playbook.md / prompts_v2.py 5 处资产，并标注 C4-iii（输入研判 + 采集策略 prompt）延至 M2 与 A3 deep-dive 一起补。
  - **04-实现预期.md 修订注（2026-04-26）**：源文档末尾追加完整对齐表（A 6 / B 12 子项 / C 9 子项 三档），每条标 ✅ / ⬆️ 现状优于预期 / 🟡 计划 M2/M3，并附文件路径锚点；引导未来读者去 `~/.claude/plans/docs-03-04-md-solguard-whimsical-ullman.md` 看完整差距评估 + 合理性判断。
  - **未触动**：`04-实现预期.md` B5.B（RAG 经验探索）+ B5.D（AST 调用链深探）+ C4-iii（输入研判 prompt）三条按合理性评估归到 M2/M3，不在本次落代码范围；M3 的 RAG 经验池需上线后 ≥100 真实 audit 案例才启动。
  - **测试就位**：`validators/audit.test.ts` 19/19 + `validators/more-info-guard.test.ts` 11/11 + `input-normalizer/normalize-contract-address.test.ts` 9/9 全绿；`npx tsc --noEmit` 零错；`src/routes/audit.test.ts` 17/24（其中 7 条 429 是**预先存在**的 supertest 同 IP 累积超限问题，已 stash-revert 验证非本次引入）。

### Changed
- **定价下调 10×（0.01 SOL → 0.001 SOL / Target）**（2026-04-25）：把 `config.auditPriceSol` 默认值、`.env` / `.env.example`（根 + server 双份）、`docs/USAGE(.zh-CN).md`、`README(.zh-CN).md`（含 "~$2" → "~$0.20" / "~$0.2"）、`solguard-server/README.md`（env 表 + API 示例 paymentUrl/amountSol）、`docs/demo/script.md`（"0.01×3→0.03" 改 "0.001×3→0.003" + "three hundredths" → "thousandths"）、前端静态文案（`public/index.html` 7 处：hero chip / how-it-works desc / price-summary unit+total / pay pane sentence+amount+btn）、`public/app.js` State fallback、`public/demo-shim.js` `DEMO_AMOUNT` 全部同步到 0.001；测试 fixture (`src/routes/audit.test.ts` 2 处、`src/notify/lark.test.ts` 1 处) 的 `paymentAmountSol` 同步到 0.001。后端运行时价格由 `AUDIT_PRICE_SOL` env → config 统一注入，`/healthz.checks.auditPriceSol` 动态回传前端，零硬编码路径。

### Added
- **Phase 6 · 测试与优化 Layer 1 推进**（2026-04-25，10/13 Task，M4 闸门 8/15 🟨）：
  - **Fixture 扩编**（`test-fixtures/real-world/` 12 份新增 + Phase 1 原 5 份 = 17 份）：Sealevel Attacks 衍生样本、Anchor examples 干净合约、Jupiter/Marinade/Metaplex 真实项目切片；每份带 SPDX + 来源注释；`test-fixtures/benchmark.yaml` 统一 `has_vuln + ground_truth + source/commit/license`；`scripts/validate_benchmarks.py` schema + 行号检查全绿。
  - **跑批 + 指标**（`scripts/run_benchmark.py` + `scripts/compare_benchmarks.py`）：跨 fixture 并发 + TP/FP/FN + Precision/Recall/F1 + summary.json/md；baseline/round1-scan/round2-prompt/round2-cached-cold/round2-cached-warm 五档存档到 `outputs/phase6-*/`。
  - **FP/FN 归因 + 规则调优**（`outputs/phase6-fp-fn-analysis.md` + `skill/solana-security-audit-skill/tools/solana_scan.py`）：`check_account_data_matching` 收窄为"原始 AccountInfo 字段 + 去重" + `_strip_comments_and_strings` 加 `lru_cache`；Round 1 F1 0.46 → 0.58。
  - **Prompt v2**（`skill/solana-security-audit-skill/ai/prompts_v2.py` + `ai/analyzer.py` 加 `prompt_version` / `SOLGUARD_PROMPT_VERSION`）：硬 rule_id 白名单 + Anchor idiom 抑制规则 + rule 消歧 + 新 few-shot（`close-without-discriminator-wipe`、未检查加减法）；Round 2 F1 → 0.71（Recall 0.94 过线，Precision 0.57 待下一轮增强）。
  - **性能 profiling + LLM 缓存**（`scripts/profile_audit.py` + `outputs/phase6-profile.md` + `ai/analyzer.py` `.llm-cache/`）：cProfile 识别 Top 3 瓶颈（semgrep 子进程 / LLM 网络 / 正则扫描）；LLM 响应缓存用 balanced-brace JSON 擦洗 + 正则消除 semgrep `time/paths/version` 非确定字段，warm 跑批 55.6s → 8.9s（6.2x 提速）；`ai/analyzer.py` 允许 `OPENAI_MODEL` / `OPENAI_BASE_URL` / `ANTHROPIC_MODEL` 覆盖，适配 OrbitAI (`gpt-5.4`) 等 OpenAI-compatible endpoint。
  - **后端日志贯穿 P6.4.2**（`solguard-server/src/task-logger.ts` 新 + `src/routes/admin.ts` 新 + `src/config.ts` + `src/server.ts` + `src/routes/audit.ts`）：`pino-http` `genReqId` 用 `X-Request-Id`（inbound 优先、否则 `randomUUID()`）并 `res.setHeader` 回显；`task-logger.ts` 暴露 `appendTaskLog` / `readTaskLogTail` / `logTaskEvent`，写入 `data/logs/{taskId}.log`（`[A-Za-z0-9._-]{1,64}` 正则校验防路径穿越 + 2 MB 软滚动）；`routes/audit.ts` 在 submit/normalize/enqueue/callback 各阶段发事件；`routes/admin.ts` `GET /api/admin/logs/:taskId` 用 `timingSafeEqual` 校验 `X-Admin-Token`（未配置 token 时 fail-closed 401）支持 `?bytes=N`（上限 2 MB）；新增 8 条 node:test + `.env.test` 增 3 个 key，server 测试 **102/102 passing**。
  - **前端 UX + 错误文案重写 P6.5（13 条微改动）**（`solguard-server/public/errors.js` 新 + `public/api.js` + `public/app.js` + `public/index.html` + `public/styles.css`）：centralized 错误字典 15 类 code → "title + hint" 二元组（VALIDATION_ERROR / WALLET_NOT_FOUND / WRONG_NETWORK / INSUFFICIENT_BALANCE / PAYMENT_VERIFICATION_FAILED / SIGNATURE_INVALID / PAYMENT_EXPIRED / NOT_FOUND / AUDIT_FAILED / NORMALIZATION_FAILED / REPO_TOO_LARGE / RATE_LIMITED / UNAUTHORIZED / INTERNAL_ERROR / NETWORK_ERROR），未知 code fallback 到原文 + 通用重试；`api.js` 在 `fetch` 失败时合成 `NETWORK_ERROR` + surface `X-Request-Id`；`app.js` 5 处 toast 替换为 `friendlyToast`（submit / wallet / pay / manual-sig / feedback）；CSS 加 `@media (prefers-reduced-motion)` + `:where(...):focus-visible` 键盘焦点环 + `[data-tip]::after` 纯 CSS tooltip + `.copy-chip`；HTML 给 email 加 `inputmode/spellcheck/autocapitalize`、manual signature 加 Enter-to-submit + 自动聚焦 + 示例 placeholder + aria-describedby；payment reference 增复制按钮；logo `<div onclick>` 改键盘可达 `<a href="#landing" role="button">`；download/print 按钮加 `data-tip`；toast 区加 `role="status"` + `aria-atomic="true"`；fail pane 显示首个 task 错误（非 batch 级）；submit 视图自动聚焦首个空 GitHub input。
  - **Layer 2 脚本预写**（`scripts/soak_test.py` + `scripts/assert_quality.py`）：soak harness 用 httpx + asyncio 轮询 20 批次，成功率/p50/p95/p_failures 落盘 `outputs/phase6-soak.json`，`--min-success 0.95` 作为 exit-code 门；`assert_quality.py` 支持 `overall` / `aggregate` / flat 三种 summary.json shape，校验 Precision/Recall/F1 ≥ 0.8 + `avg_duration_s` ≤ 300 + `degraded_count = 0`（可 `--allow-degraded`）；两个脚本 `python -m py_compile` + `--help` 通过，上线后一键验收。
  - **三文档 + LICENSE-THIRD-PARTY 联动**：[07-Phase6-测试与优化.md](../docs/04-SolGuard项目管理/07-Phase6-测试与优化.md) 11 个 Task 验收标准勾到位 + "✅ 验收结论" 补注 + "🟨 Layer 2 阻塞" 标记 3 项 + 阶段结论；[01-WBS工作分解结构.md](../docs/04-SolGuard项目管理/01-WBS工作分解结构.md) Phase 6 `0/13 ⏳ → 10/13 🟨` + 工时地图表新增"完成"列；[09-里程碑与交付物清单.md](../docs/04-SolGuard项目管理/09-里程碑与交付物清单.md) M4 `0/15 ⏳ → 8/15 🟨`；`LICENSE-THIRD-PARTY.md` 维护 Sealevel Attacks + Anchor examples + 真实项目切片的 Attribution。

- **Phase 4.6 · Submit Target / Batch 重构**（2026-04-25，2/2 Task）：按用户需求把 Submit 表单改成"显式列出 4 个可提交栏目（GitHub / Program Address / Whitepaper / Website）+ 新增 More Info（自由文本 ≤ 2000 字）+ 1–5 Audit Target 按数量计费 + 单笔支付覆盖"。
  - **后端 Batch 模型**（`solguard-server/src/types.ts` / `src/storage/batch-store.ts` 新 / `src/validators/audit.ts`）：新增 `AuditBatch { batchId, taskIds[], totalAmountSol, paymentReference, paymentSignature?, ... }`；`AuditTask` 追加 `batchId?`；`InputType` 新增 `'more_info'`；`AuditTarget` 类型 + `targetSchema.refine` 强制每个 Target **至少填 1 个主字段**（GitHub / Program Address / Whitepaper / Website），moreInfo 仅补充；`createBatchSchema` 要求 `targets: [1, 5]` + email；`InMemoryBatchStore` 镜像 `task-store` 模式。
  - **批量 API**（`src/routes/audit.ts`）：`POST /api/audit` 接受 `{ targets, email }`（新）或 `{ inputs, email }`（旧，自动包装成单 Target batch）→ 创建 1 个 `AuditBatch` + N 个 `AuditTask`，共享 paymentReference，金额 = `N × config.auditPriceSol`；FREE_AUDIT 模式下 batch + 所有 task 直接 `paid` 并入队；新增 `GET /api/audit/batch/:batchId` → `{ batch, tasks }`；新增 `POST /api/audit/batch/:batchId/payment` → 一次签名覆盖整个 batch，成功后把所有 task `paying → paid` 并 `normalizeAndEnqueue`；旧 `POST /api/audit/:taskId/payment` 保留但在检测到 `batchId` 时内部路由到 batch 分支（向后兼容）；响应体在创建时加 `taskId` 别名（= `taskIds[0]`）保留 pre-P4.6 客户端兼容。
  - **Audit Engine prompt**（`src/audit-engine.ts`）：`buildAuditPrompt` 新增 `formatMoreInfo` 帮助函数，把所有 `more_info` 输入拼成独立的 `## Additional Context (user-provided)` 段并带提示"不要抓取 URL，仅作背景参考"；`formatInputs` 过滤 `more_info`。
  - **Input normalizer**（`src/input-normalizer/index.ts`）：`normalize()` 显式抛错 `more_info is context-only`，`normalizeAll()` 先 `filter((inp) => inp.type !== 'more_info')` 再并发 normalize（保证 more_info 不进 RustAnalyzer / Solana RPC / whitepaper-extractor 等 scanner 通道）。
  - **Payment poller**（`src/payment-poller.ts`）：全文重写 `startPaymentPoller`，优先按 `batchStore.list({status:'paying'})` 轮询批次，验证通过后把 batch 下**所有** task 翻 `paid` 并逐个 `normalizeAndEnqueue`；保留 orphan task（无 batchId，升级前创建）的遗留分支兜底。
  - **Payment core**（`src/payment.ts`）：`createPaymentRequest` 参数加 `label?` / `message?`，batch 场景传 `SolGuard Batch` + `N target(s)` 信息。
  - **健康检查**（`src/routes/health.ts`）：`/healthz.checks.auditPriceSol` 暴露当前单价，供前端 `#price-summary` 动态渲染 `N × price`。
  - **前端 3 页面重构**（`public/index.html` / `public/app.js` / `public/api.js` / `public/styles.css`）：
    - **Submit**：`#targets-list` 取代 `#inputs-list`，每张 Target 卡片显式 5 字段（GitHub / Program Address / Whitepaper / Website 用 `<input>`，More Info 用 `<textarea>` + 2000 字符计数器），`#btn-add-target`（上限 5）+ 单卡删除按钮；`#price-summary` 随 Target 数量实时刷新 `N × 0.01 SOL`（单价从 `/healthz.checks.auditPriceSol` 取，零网络请求时 fallback 0.01）。`form.onsubmit` 调 `api.createAudit({ targets, email })` → `resp.batchId` → `Router.go('progress', { batchId })`。
    - **Progress**：上半 `#pay-pane` 改为 batch 付款（金额/收款方/reference 全部用 batch 字段，钱包余额检查 vs `totalAmountSol`）；下半 `#audit-pane` 改为任务列表，每个 task 一行（`Target #i` 摘要 + 独立进度条 + 状态 badge）+ 汇总条 = `avg(pct)`；`handlePay()` 调 `api.pushBatchPayment(batchId, sig)`；`startPolling(batchId)` 每 2s 调 `api.getBatch` 刷新全部行。
    - **Report**：顶部新增 `#target-tabs` 切换 Target（N=1 时隐藏）；切 Target 时重取该 task 的 md + stats + findings，沿用既有 Summary / Assessment / Checklist 三 sub-tab；feedback 按钮带 `batchId` + `taskId`。
    - **路由**：参数改名 `batchId`（`#progress/:batchId` / `#report/:batchId`）；老 `#progress/:taskId` / `#report/:taskId` 访问时 `resolveBatchParam()` 自动 `api.getTask(taskId)` → 拿 `batchId` → `Router.go(section, { batchId })` 重定向（客户端升级，服务端零改动）。
    - **API 封装**（`public/api.js`）：`createAudit(body)` 请求体换为 `{ targets, email }`；新增 `getBatch(batchId)` / `pushBatchPayment(batchId, signature)`。
    - **Styles**（`public/styles.css`）：新增 `.target-card / .target-header / .target-badge / .target-del / .target-fields / .target-field-row / .tf-label / .tf-icon / .tf-input / .tf-counter / .tf-error`、`.price-summary / .ps-left / .ps-breakdown / .ps-amount`、`.task-list / .task-row / .tr-head / .tr-summary / .tr-pct / .row-failed / .row-completed`、`.target-tabs / .target-tab / .tt-idx / .tt-label / .tab-failed`；响应式 `@media` 规则同步调整。
  - **测试**（`src/routes/audit.test.ts` + `src/validators/audit.test.ts`）：新增 **18 条单测**——`targetSchema` 7 条（接受 github + moreInfo / 拒绝 moreInfo-only / 拒绝空 / 拒绝 moreInfo > 2000 / 接受 = 2000 / 拒绝 bad github / 拒绝 bad solana address）、`createBatchSchema` 3 条（接受 1-5 / 拒绝 0 / 拒绝 >5）、`targetToInputs` 2 条（映射 / 跳过 undefined）、路由 5 条（batch 创建 taskIds + amountSol + FREE_AUDIT enqueue / 拒绝 >5 targets / 拒绝 moreInfo-only / 拒绝 moreInfo>2000 / `GET /api/audit/batch/:id` 聚合）+ 1 条 GET batch 404；`pnpm --filter solguard-server run lint && run build && run test` **93/93 passing**（Phase 5 Day 12 的 75 + 18 新增），lint + build 零错。
  - **文档三联动**：[docs/04-SolGuard项目管理/05-Phase4-前端UI开发.md](../docs/04-SolGuard项目管理/05-Phase4-前端UI开发.md) 追加 §P4.6（P4.6.1 / P4.6.2 双 Task 含验收结论）·[01-WBS工作分解结构.md](../docs/04-SolGuard项目管理/01-WBS工作分解结构.md) Phase 4 `10/10 → 12/12` + 总计 `81/48 → 83/50 (60%)` ·[09-里程碑与交付物清单.md](../docs/04-SolGuard项目管理/09-里程碑与交付物清单.md) M2 `20/21 → 22/23 🟨`（追加 2 项前端交付物）。

### Added
- **Phase 5 · Day 12 集成与联调（三阶段通知 + 客户邮件升级 + OpenAPI 对齐）**（2026-04-24）：
  - **Lark 三阶段 webhook 通知模块** `solguard-server/src/notify/lark.ts`：导出 `notifyScanRequested / notifyPaymentConfirmed / notifyScanCompleted / notifyScanFailed` 4 个函数 + `postOperatorAlert`（运维告警，不受 stage 白名单限制）；内部统一 `postCard()` 写入 `msg_type: 'interactive'` 卡片，根据 `task.statistics.critical/high` 自动着色（crit→red / high→orange / else→green）；无配置静默 return、non-2xx + fetch throw 仅 warn 不抛；`LARK_WEBHOOK_URL` / `LARK_NOTIFY_STAGES` / `LARK_ENV_TAG` 三个新 env 驱动。配套 `notify/lark.test.ts` 7 条 node:test mock fetch（未配置零 fetch / envTag 前缀 / stage 白名单 / non-2xx 吞异常 / throw 吞异常 / 严重度着色 / operator alert 绕开白名单）。
  - **三阶段插桩**（全部 fire-and-forget）：
    - Stage 1 submitted — `src/routes/audit.ts` 的 FREE_AUDIT 分支 + paying 分支分别在 `res.status(201)` 前调 `notifyScanRequested`。
    - Stage 2 paid — `src/payment-poller.ts` `processTask` 在 `opts.onPaid(updated)` 前调 `notifyPaymentConfirmed`；`src/routes/audit.ts` `POST /audit/:id/payment` 成功后同步调。
    - Stage 3 completed/failed — `src/audit-engine.ts` `onAuditFinished` 结尾按 `task.status` 分支调 `notifyScanCompleted` 或 `notifyScanFailed`。
    - 顺带修补：`payment-poller.ts` 支付超时 `status=failed` 分支以前不触发 `onAuditFinished`，失败邮件 + Lark 卡都发不出来；现补 `getAuditEngine().onAuditFinished(failed)`。
  - **客户邮件升级** `src/email.ts`：
    - `renderAuditEmail` 拆成 `renderCompletedEmail` + `renderFailedEmail` 两条模板路径（failed 态文案提示"回复本邮件获取支持"，链接改红色）。
    - `reportUrl` / `feedbackUrl` 改用 `config.publicBaseUrl + '/#report?taskId=...'` / `#feedback?taskId=...`，对齐 Phase 4 前端 hash 路由。
    - `buildAttachments` 双附件：`solguard-<taskId>.md` +（completed 时）`solguard-<taskId>.json`（包含 `statistics/findings/reportUrl/completedAt/inputs` 结构化快照）。
    - `sendMail` 新增 `replyTo`（`EMAIL_REPLY_TO`）+ `bcc`（`EMAIL_BCC_OPERATOR`，自动排除等于 `to` 的地址）。
    - 3 次重试全败后在 `queue.delete` 前调 `postOperatorAlert({ template:'red', ... })` 推红卡（绕开 `LARK_NOTIFY_STAGES`，运维必须看到）。
  - **OpenAPI / Swagger UI**：`openapi.yaml` 版本 `0.1.0 → 0.5.0`；补 `info.description` 三阶段生命周期说明 + MIT license + 顶层 `security: []`；`PaymentPushRequest` 单独作为 schema（从 inline 提取）；`npx @redocly/cli@1 lint openapi.yaml` **零 error**（仅 15 条低优先 warning）。新增 `public/docs.html`（Swagger UI 5.x unpkg CDN 指向 `/openapi.yaml`）+ `package.json` `postbuild` 钩子自动把 `openapi.yaml → public/openapi.yaml`。
  - **一次性 SMTP 验证脚本** `scripts/send-test-email.ts`：`npx tsx scripts/send-test-email.ts you@example.com` 构造 fake `AuditTask` 跑 `enqueueAuditEmail`，用来独立验证 QQ/Gmail SMTP 通道（不触发真扫描）。
  - **配置面** `src/config.ts`：新增 `larkWebhookUrl / larkNotifyStages / larkEnvTag / emailReplyTo / emailBccOperator` 5 个 zod 字段；两份 `.env.example`（`solguard-server/.env.example` + 仓库根 `.env.example`）补齐对应占位 + goat-track smtp.qq.com:465 提示注释。
  - **构建/测试**：`npm run build` + `postbuild` 静态同步通过；`npm test` **75/75 passing**（比 Phase 4 的 68 新增 7 条 Lark mock 测试）；`npx @redocly/cli@1 lint openapi.yaml` 零 error。
  - **Attribution**：`src/notify/lark.ts` 移植自 `GoatGuard/agent-server/feishu-integration.ts` 的 `sendWebhookRichAlert / notifyScanStarted / notifyScanCompleted` 三函数，删除 bitable / docx_builtin_import / im_v1 分支，仅保留 incoming webhook 路径；登记在 `LICENSE-THIRD-PARTY.md` Attribution 表新增第 8 行。

### Added
- **Phase 4 前端 UI 完整实现**（2026-04-24，10/10 Task 一次性交付，M2 里程碑前端侧全绿）：
  - **模块化 Vanilla JS** 7 个文件（`solguard-server/public/`）：`index.html`（5 section 骨架 + Inter/IBM Plex Mono + Solana web3 IIFE）、`styles.css`（CSS 变量设计 token，Solana 品牌紫 `#7c3aed` + 绿 `#14f195`）、`app.js`（hash Router + 5 section 生命周期 + Toast + 状态机）、`api.js`（同源 fetch 封装，错误透传 `{code,message}`）、`wallet.js`（Phantom detect/connect/disconnect + accountChanged 订阅 + 余额查询）、`payment.js`（`SystemProgram.transfer` + reference key + `signAndSendTransaction` + confirmTransaction 新签名）、`report.js`（marked v11 + highlight.js 懒加载；三 Tab 切分 Risk Summary / Full Assessment / Checklist；自动补 heading IDs）。
  - **Landing / Submit / Progress / Report / Feedback** 5 个 Section：
    - Submit：动态 1–5 行输入（4 type 下拉 + 值），前端校验完全对齐 `validators/audit.ts` 的 Zod schema（GitHub URL 正则、Solana base58 32–44、URL 格式、email）；同意勾选、防重复提交、行内 `.input-error`。
    - Progress：先显示支付面板（taskId/network/amount/recipient/reference 全展示），Phantom 连接 + `payAudit()` 一键签 → 推 `/api/audit/:id/payment` → 5 步进度条（Queued/Parse/Scan/AI/Report）每 2s 轮询 `GET /api/audit/:id`，读 `progressPercent` 驱动 `.progress-bar .fill`。离页自动 `clearInterval` 防泄漏。提供"手工粘贴 signature"降级入口（Plan B）。
    - Report：`GET /api/audit/:id/report.md` + `/report.json` 并发拉取，findings 侧栏按严重度分组、锚点跳转；D/C/B/A/S 评级徽章（`ratingFromStats` 依赖 statistics）；`<Blob>` 下载 .md/.json；`window.print()` 打印样式；`@media print` 隐藏导航。
    - Feedback：5 星 radio（roving-tabindex）+ 文本 + 邮箱可选；提交后表单折叠为 Thank You 态，防重复提交。
  - **Solana Pay 流程打通**：buildPaymentTx 构造 transfer ix 并把 `reference` 作为 readonly non-signer key 附加，和后端 `validateTransfer` 一致；`signAndSendTransaction` 优先、`signTransaction` 降级；`confirmTransaction({signature,blockhash,lastValidBlockHeight}, 'confirmed')` 新签名 + polling fallback，90s 超时兜底。
  - **Health / FREE_AUDIT / 集群感知**：启动时 `GET /healthz` 读 `checks.solanaCluster` + `checks.freeAudit`，顶部 chip 自动显示集群，FREE_AUDIT 模式在 Landing stats 插"🎁 Free"条目并跳过支付面板（服务器已把 status 设为 `paid`）。
  - **路由**：`#landing` / `#submit` / `#progress/{taskId}` / `#report/{taskId}` / `#feedback/{taskId}`；刷新保留 section + taskId，浏览器后退正常。
  - **Attribution**：`solguard-server/public/styles.css` + `app.js` 的组件模式（`.card`/`.btn-primary`/`.status-badge`/`.progress-bar`/`.findings-grid` 5 列/`.toast`/`.spinner`/`fadeUp`）来自 GoatGuard（MIT）的单页 UI，重写为 Solana 色板与 Solana Pay（非 x402）流程；登记在 `LICENSE-THIRD-PARTY.md` Attribution 表新增第 7 行。

### Added
- **Phase 3 后端服务完整实现**（2026-04-22，13/13 Task 一次性交付，`bash scripts/verify-phase3.sh` **39 项全绿**，`npm test` **68/68 passing**，`npm run lint` / `typecheck` / `build` 零错）：
  - **双路径 runner**（对齐 Phase 2 实际交付的 AI-first 6 步流水线）：
    - 默认 `oh -p`（Agentic）：`src/audit-engine.ts` 的 `buildAuditPrompt()` 精确引用 5 个工具 `solana_parse → solana_scan → solana_semgrep → solana_ai_analyze → solana_report`，`TOOL_STATUS_MAP` 百分比 25/40/55/75/95。
    - 降级 `run_audit.py` 子进程：新建 `src/runners/python-runner.ts`（+`python-runner.test.ts` 4 条 node:test），扩 `scripts/run_audit.py` 支持 `--inputs-json` / `--callback-url` / `--callback-token` / `--emit-events`；`audit-engine.ts` 在 `FREE_AUDIT=true` / `oh` 不可用 / 重试失败时自动切换，`lastErrorKind ∈ {oh_unavailable, oh_timeout, oh_nonzero, python_failed}` 供日志定位。
    - Skill 工具注册：新建 `skill.yaml` 清单 + `ai/analyzer_tool.py`（`AIAnalyzer.cross_validate_and_explore` 的薄 Tool 包装）+ `scripts/oh_skill_smoke.sh`（导入 + `execute` 冒烟）。
  - **四类输入规整层 `src/input-normalizer/`**（github / contract_address / whitepaper / website 全覆盖 + 递归）：
    - `normalize-github.ts`：`git clone --depth=1`（120s 超时）+ BFS 找 `programs/*/src/lib.rs`（Anchor 优先）→ `rust_source`。
    - `normalize-contract-address.ts`：`Connection.getAccountInfo(PublicKey)` 拉字节码 → 写 `.so` → `bytecode_only`。
    - `normalize-url.ts`：`fetch` + HTML 剥离（保留 `href`/`src`）+ 正则/LLM lead 抽取（GitHub URL + Solana 地址）→ 发现 lead 递归 `normalize`，否则 `lead_only`。
    - 并联 `normalizeAll()` 在 `POST /api/audit` 异步执行，失败单条记 `normalizeError`、全部失败才标 `failed`。4 份单测（`normalize-{github,contract-address,url,recursive}.test.ts`）共 15 用例。
  - **3 条补齐路由 `src/routes/audit.ts`**：
    - `POST /api/audit/:taskId/payment`：客户端 push 签名直验，缩短"paying→paid"延迟；on-chain 校验失败仅返回 `{ok:false}`（不改 status，让 poller 续观察）。
    - `GET /api/audit/:taskId/report.md`：`Content-Disposition: attachment` + `text/markdown; charset=utf-8`。
    - `GET /api/audit/:taskId/report.json`：`toPublicReport()` 只暴露 `{taskId, status, inputs, statistics, findings, reportUrl, progress, timestamps}`，**不**返回 `email / paymentSignature / agentCallbackToken`。
    - `audit.test.ts` supertest 追加 10 条（payment 4 / report.md 3 / report.json 3）。
  - **安全加固**：
    - `POST /api/audit/:taskId/complete` 新增 `X-Agent-Signature: sha256=<hex>`（HMAC-SHA256 over raw body keyed by `AGENT_CALLBACK_TOKEN`），`createApp()` 用 `express.json({verify})` 捕获原始字节；legacy `X-Agent-Token` 仍兼容，但 `AGENT_HMAC_REQUIRED=true` 或 `NODE_ENV=production` 时强制签名。`audit.test.ts` 新增两条 HMAC 用例（合法 / 篡改）。
    - `src/middleware/rate-limit.ts`：内存 sliding-window 限流，默认 10 req/60s/IP，挂到 `POST /api/audit` 与 `POST /api/feedback`；`rate-limit.test.ts` 3 条覆盖 disabled / exceed / custom keyFor。
  - **环境变量扩展**：`.env.example` 新增 `AGENT_HMAC_REQUIRED` / `AUDIT_OUTPUT_ROOT` / `RUNNER_FALLBACK_TO_PYTHON` / `PYTHON_BIN` / `PYTHON_RUN_AUDIT_SCRIPT` / `GIT_BIN` / `INPUT_NORMALIZER_TIMEOUT_MS` / `RATE_LIMIT_{ENABLED,WINDOW_MS,MAX_REQUESTS}`；`src/config.ts` Zod schema 同步 10 个新字段。
  - **文档交付**：新建 `solguard-server/README.md`（Quick Start + 环境变量表 + 8 路由文档 + 双路径说明）；新建 `solguard-server/openapi.yaml`（OpenAPI 3.0，覆盖 8 路由 + 安全方案 AgentSignature/AgentToken）；扩 `scripts/verify-phase3.sh` 新增"Phase 3 新模块"节 + 4 条路由冒烟 + `oh_skill_smoke.sh` 钩子。
  - **外部阻塞单独跟踪**（不阻断进入 Phase 4）：P3.4.4 Devnet 真钱包扫码支付（poller + push 路由代码已就绪）、P3.5.1 真 SMTP 发邮件（mailer + 模板 + 重试已就绪）。

### Changed
- **Phase 2 AI-first 重塑**（2026-04-22，规划文档层，代码尚未动）：对齐上游
  `Contract_Security_Audit_Skill`（MIT）的"脚本只做数据采集、AI 判断 + 写作"
  哲学，把 Phase 2 从 22 Task / 34h 重构为 13 Task / 25h。核心变化：
  - **删除交付物**（计划中）：`tools/rules/*.py` 7 个规则类文件、`tools/reporters/*.py`
    3 个 md 渲染器、`BaseRule` / `RuleRegistry` 抽象层、独立 Kill Signal 工具、
    独立 JSON Schema 校验层、tree-sitter 升级（延至 Phase 6）。
  - **新增交付物**：`tools/semgrep_runner.py`（原始 semgrep JSON 直接喂 AI）、
    `assets/semgrep-rules/` 目录（3–5 条 Anchor yaml 规则）、`ai/analyzer.py`
    的 `cross_validate_and_explore` 双角色方法（交叉验证 scan hints + 探索式
    补漏一次 LLM 调用完成）。
  - **合并 / 改写**：`tools/solana_scan.py` 单文件内 7 个**纯函数**替代 8 个
    Task 拆分的规则类；规则权威源改为 `references/vulnerability-patterns.md`
    （markdown 文档）；Markdown 报告由 AI 按 `references/report-templates.md`
    直接写入，Python 只做落盘 + sha256 + webhook。
  - **容错三铁律**：所有 tool 不抛异常、返回带 `error` 字段的降级结构；
    semgrep 缺失不阻塞主流程；LLM 不可用仍出 `decision="degraded"` 报告
    （`scripts/e2e_smoke_degraded.sh` 专项闸门）。
  - **文档同步**：`docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md`
    新增 §重塑说明 + mermaid 数据流图；`01-WBS工作分解结构.md` P2 `22/32h`
    → `13/25h`、总计 `88/140h` → `79/133h`；`09-里程碑与交付物清单.md`
    M1 交付项 `4/17` → `4/13`。

### Added
- **M1 闸门达成 — Phase 2 剩余 9 Task 一次性交付**（2026-04-22）：
  - `mypy --strict -p core -p tools -p ai` = **0 error**；
    `pytest --cov=tools --cov=ai --cov=core` = **86%** coverage；
    `bash scripts/e2e_smoke.sh` + `bash scripts/e2e_smoke_degraded.sh`
    双闸门全绿；`outputs/phase2-baseline/` 归档 5 fixture × 4 产物 = 20 文件。
  - 覆盖任务：P2.2.3 / P2.3.1 / P2.3.2 / P2.3.3 / P2.4.1 / P2.4.2 /
    P2.5.1 / P2.6.1 / P2.6.2（见下文分条记录）。
- **P2.6.2 — E2E 冒烟 + degraded 闸门**（2026-04-22）：
  - `skill/solana-security-audit-skill/scripts/run_audit.py`（in-process
    七步编排：parse → scan → semgrep → AI → findings → markdown → report；
    支持 `--degraded` 强制 LLM 跳过）。
  - `scripts/assert_smoke.py` 对 `ground_truth.yaml` 全维度断言：
    必需文件存在 / `report.json` 可被 `ScanResult.from_dict()` 反序列化 /
    `confirmed ≥ expected_ai_confirmed_min`（非 degraded）/
    `scan_rule_ids ⊇ expected_scan_rule_ids`（scan 兜底）/
    degraded 模式 `risk_summary.md` 顶部含 `DEGRADED — LLM unavailable`
    banner。
  - `scripts/e2e_smoke.sh` + `scripts/e2e_smoke_degraded.sh` 双路径：
    正常模式 token 单次 < 5K / 端到端 < 2 min；degraded 模式 scan hints
    占位报告仍满足契约。
  - 产物归档：5 fixture × 4 文件落在 `outputs/phase2-baseline/{fixture}/`
    作为后续 Phase 3+ 的 regression baseline。
- **P2.6.1 — `ground_truth.yaml` schema 扩列**（2026-04-22）：
  - `SolGuard/test-fixtures/contracts/ground_truth.yaml` 为 5 fixture
    全部补齐 `expected_scan_rule_ids / expected_ai_confirmed_min /
    expected_ai_confirmed_max / expected_severity_gte /
    expected_report_files` 五列；原 `expected[]` 字段保留给 Phase 6
    benchmark 做向后兼容。
- **P2.5.1 — `solana_report.py` 纯落盘器**（2026-04-22）：
  - `skill/solana-security-audit-skill/tools/solana_report.py`：
    `persist()` + `SolanaReportTool` 零 Markdown 模板字面量，仅做
    mkdir → 写三份 md → sha256 + bytes → 写 `report.json`（首次含
    `ScanResult`，其后合并 `ReportBundle` + `Callback` 再回写）→
    可选 webhook（`httpx.post` 超时 30s，失败写 `Callback.status=failed`
    不抛）。
  - `tests/test_report.py` 7 用例：文件齐全 + sha256 对账 +
    `report.json` round-trip + callback skipped/failed/exception 三态 +
    空 md + 并发 task_id 独立。全部 PASS。
  - `tools/__init__.py` 暴露 `SolanaReportTool / report_persist /
    report_execute`。
- **P2.4.2 — Kill Signal 对抗测试 + LLM 降级路径**（2026-04-22）：
  - `tests/fixtures/adversarial/fake_missing_signer.rs`（上层
    `require_keys_eq!` 已验签的 false-positive 陷阱）+
    `real_arbitrary_cpi.rs`（浓缩 kill-signal 的 CPI 真漏洞）。
  - `tests/test_ai_kill_signal.py` 6 用例：
    - live: `real_arbitrary_cpi` → `confirmed[*].rule_id=arbitrary_cpi`
    - live: `fake_missing_signer` → `rejected` 或 `is_valid=False`
    - offline: `httpx.TimeoutException` mock → `parse_error` 非空 +
      `confirmed=[]`（0 token 消耗）
    - offline: 无 API key → 同上
    - offline: 破损 JSON 被 `json_repair` 救活
    - offline: 纯 garbage → `parse_error` 非空、不抛
  - 离线 6 case 全绿；`-m live_llm` 需 API key 时额外通过。
- **P2.4.1 — `ai/prompts.py` + `ai/analyzer.py`**（2026-04-22）：
  - `ai/prompts.py`：`SOLANA_AUDIT_SYSTEM_PROMPT`（身份 + 7 类漏洞 +
    双角色 + 硬 JSON schema ≥ 20 行 + 2 条 few-shot）+
    `SOLANA_AUDIT_USER_PROMPT_TEMPLATE` + `build_user_prompt()` helper。
  - `ai/analyzer.py`：`AIAnalyzer.cross_validate_and_explore()` 一次
    LLM 调用同时做「交叉验证 scan hints」+「探索式补漏」两件事；
    支持 Anthropic `claude-3-5-sonnet-20241022` 主链 + OpenAI
    `gpt-4o` 备链，`tenacity` 重试 ×2、超时 60s；JSON 解析三段式
    `json.loads` → `json_repair.loads` → 结构化降级返回 `parse_error`，
    永不抛。Token 用量打印到日志。
  - `ai/__init__.py` 暴露 `AIAnalyzer / DEFAULT_ANTHROPIC_MODEL /
    DEFAULT_OPENAI_MODEL / SOLANA_AUDIT_SYSTEM_PROMPT /
    SOLANA_AUDIT_USER_PROMPT_TEMPLATE / FEW_SHOT_EXAMPLES /
    build_user_prompt`。
  - `uv run mypy --strict -p ai` → Success: no issues found in
    3 source files。
- **P2.3.3 — scan + semgrep 单元测试**（2026-04-22）：
  - `tests/test_scan.py` 14 用例：5 fixture × `expected_scan_rule_ids ⊆
    actual_rule_ids`（对齐 ground_truth）+ 3 clean 零误报 + 3 规则
    smoke + 1 单规则 raise 隔离 + 1 空 ParsedContract 不崩 + 1 wrapper
    对账。`tools.solana_scan` 覆盖率 **88%**。
  - `tests/test_semgrep.py` 6 用例：live semgrep 对 01 fixture ≥ 1
    命中（`skipif(not shutil.which("semgrep"))`）+ 4 降级路径（非法
    rules_dir / 非法 target / 缺 binary / 空规则目录）+ wrapper 契约。
- **P2.3.2 — `semgrep_runner.py` + 4 条 Solana 规则**（2026-04-22）：
  - `skill/solana-security-audit-skill/tools/semgrep_runner.py`（146 行）：
    薄 CLI wrapper，**不做结果二次加工**，把原始 semgrep JSON 直接喂 AI。
    容错：未安装 / 超时 60s / rules_dir 缺失 / 非法 JSON 均返回
    `{"results": [], "tool_error": "<reason>"}` 不抛；部分规则 parse 失败
    （exit=2 但 stdout 合法）时保留成功命中的结果并把错误数量记进
    `tool_error`。
  - `skill/solana-security-audit-skill/assets/semgrep-rules/` 新建目录，
    4 条 Rust/Anchor AST 规则（全部 `semgrep --validate` 通过）：
    - `solana-unchecked-account.yaml` — `AccountInfo`/`UncheckedAccount`
      字段（01/02/04 fixture 均命中）
    - `solana-raw-arithmetic.yaml` — `vault.balance = vault.balance ± x`
      on `balance`/`amount`（03 fixture 2 命中）
    - `solana-manual-deserialize.yaml` — `AnchorDeserialize::deserialize`
      / `try_from_slice` / `BorshDeserialize`（02 fixture 命中）
    - `solana-invoke-without-pda-check.yaml` — `invoke_signed(&$IX, …)`
      调用（04 fixture 命中）
  - Attribution：`LICENSE-THIRD-PARTY.md` 新增 2 行（semgrep_runner.py + 规则目录）
    登记上游 `Contract_Security_Audit_Skill/skill/scripts/semgrep_runner.py`
    (MIT) 的结构借鉴与 rpc_common 依赖裁剪说明。
- **P2.3.1 — `solana_scan.py` 7 纯函数 hints 扫描器**（2026-04-22）：
  - `skill/solana-security-audit-skill/tools/solana_scan.py`（420+ 行）：
    7 个 `check_*(parsed) -> list[hint]` 纯函数：`missing_signer_check`、
    `missing_owner_check`、`integer_overflow`、`arbitrary_cpi`、
    `account_data_matching`、`pda_derivation_error`、`uninitialized_account`。
    AI-first：每条 hint `confidence="low"`，final verdict 交 AI 交叉验证。
  - 聚合器 `scan()` + `SolanaScanTool` + `execute()`；单条规则抛异常仅记
    `scan_errors`、不阻塞其他规则；hints 按 `(rule_id, location)` 去重；
    `statistics` 按 rule_id 分桶。
  - 5 fixture smoke：01→missing_signer×1、02→missing_owner+account_data_matching、
    03→integer_overflow×2、04→arbitrary_cpi×1、05→0 hints（clean 0 误报）。
  - `tools/__init__.py` 新增导出 `SolanaScanTool / scan / scan_execute`。
- **P2.2.3 — `test_parse.py` parse 层单元测试**（2026-04-22）：
  - `skill/solana-security-audit-skill/tests/test_parse.py`（17 用例）：
    5 fixture 结构断言 + 4 降级路径（空串 / whitespace / 非 Rust 文本 /
    `None` 输入 / 文件不存在）+ round-trip（`ParsedContract.to_dict() →
    from_dict()` 幂等 × 5 fixture）+ 泛型保留（`Account<'info, Vault>`）+
    `execute` wrapper 对账。
  - `tests/conftest.py` 新增 `FIXTURES_ROOT` / `fixture_path()` /
    `load_ground_truth()` / `fixtures_root` / `ground_truth` fixture，
    消除 skill→repo 根路径硬编码。
  - 覆盖率：`tools.solana_parse` **84%**（≥80% 闸门），17 tests 全绿。
- **Prep（AI-first 重塑清理，2026-04-22）**：
  - 删除 `skill/solana-security-audit-skill/tools/rules/` + `reporters/`
    整个目录（规则类抽象与 md 渲染器淘汰）；`pyproject.toml` wheel
    `packages` 移除 `reporters`。
  - `pyproject.toml` 新增 `json-repair>=0.28.0` 运行时依赖；`pytest.ini_options`
    新增 `live_llm` marker；`uv sync` 成功。
- **P2.2.1 — `solana_parse.py` Anchor/Native-Rust 结构提取器**（2026-04-22）：
  - `skill/solana-security-audit-skill/tools/solana_parse.py` 从 83 行
    骨架扩到 597 行：纯 stdlib (re + pathlib) 实现的 MVP 解析器，返回
    `core.types.ParsedContract`。提取维度 6 项：`functions`（含 is_pub
    / args / return_type / body_start / body_end 偏移）、`accounts`
    （含字段名 / 类型原文 / `type_category` 归类 / 每字段关联的
    `#[account(...)]` 属性块）、`instructions`（`#[program] mod` 内的
    pub fn，带 program_mod 反向索引）、`anchor_attrs`（全文 `#[account]`
    扁平列表）、`metadata`（parser 版本 / line_count / declare_id /
    program_mod / anchor prelude 指示）、`parse_error`（非致命降级通道）。
  - 关键鲁棒性设计：
    - `_strip_comments`：行注释 + 块注释替换为等长空格，保持 byte offset
      和 `line` 计算稳定；避免 `//` 内的 `{` / `"` 干扰大括号匹配。
    - `_balanced_block`：按大括号深度扫描，支持 `fn f() { match x {} }`
      等嵌套体；替换原先不可靠的 `re.search('{.*?}')`。
    - `_find_account_attrs`：按圆括号深度扫描 `#[account(...)]`，正确
      处理嵌套 `[]`（如 `seeds = [b"vault"]`，这在 Phase-2 测试 fixture
      中直接出现）。
    - `_read_type_until_comma`：按 `<> () []` 三重深度扫描类型边界，
      保证 `Account<'info, Vault>` 里的顶层逗号不被误当字段分隔。
    - `parse_source` 总函数：空串 / None / 非 Rust 文本 / 解析异常
      全部降级为带 `parse_error` 的空 `ParsedContract`，**永不抛**。
  - `tools/__init__.py` 暴露 `SolanaParseTool` / `execute` /
    `parse_file` / `parse_source` 四个符号。
  - 验证（手动脚本，P2.2.3 将搬到 pytest）：
    - `01_missing_signer.rs` — fns=1, accts=1，`authority` 字段
      `type_category=AccountInfo`（未来 `missing_signer_check` 能命中）
    - `02_missing_owner.rs` — fns=1, accts=1，`config` 字段 `AccountInfo`
    - `03_integer_overflow.rs` — fns=2, accts=1, instructions=2
    - `04_arbitrary_cpi.rs` — fns=1, accts=1, **seeds=1**（`b"vault"`）
    - `05_clean_contract.rs` — fns=3, accts=3, **seeds=3**，`vault`
      字段属性 `init + seeds + bump` 全部识别
  - 质量门：`uv run mypy --strict -p tools` → Success（5 源文件零
    error）；5 fixture 全部 `ParsedContract.from_dict(out).to_dict() == out`
    往返等值；异常输入 4 路径全部降级不崩。
- **P2.1.3 — core/types.py 扩写 + 测试收敛**（2026-04-22）：
  - `skill/solana-security-audit-skill/core/types.py` 从 174 行扩到
    394 行：补齐 `Statistics / ScanResult / ScanTask` 缺失的
    `from_dict`；按 SKILL.md §Output Contract + `references/report-templates.md`
    新增 4 个 Solana 专属 dataclass — `AuthorityInfo`（mint / freeze /
    update / program-upgrade 四槽 + extensions）、`TokenExtension`
    （含 `red_flag` + `severity_hint`）、`ReportBundle`（三级 md +
    report.json 路径 + sha256 + bytes）、`Callback`（webhook 状态机）；
    `ScanResult` 新增 6 字段（`authority / inputs_summary /
    source_visibility / decision / reports / callback`），全部可选以
    保持向后兼容。
  - `core/__init__.py` `__all__` 同步追加 `AuthorityInfo / Callback /
    ReportBundle / TokenExtension` 4 个符号，公共 API 合计 11 个。
  - `tests/test_types.py` 从 3 用例扩到 16 用例：覆盖所有 Enum 的
    `from_value` 正常/异常路径、所有 dataclass 的 round-trip、
    `source_visibility=bytecode_only → decision=degraded` 降级链路、
    `Callback.status` / `ScanResult.decision` 非法值抛 `ValueError`。
  - 质量门：`uv run pytest tests/test_types.py -v` 16 passed in 0.03s；
    `uv run mypy --strict -p core` Success: no issues found in 2
    source files（strict 口径限 core/，避免历史类型债连带爆炸）。
  - 约束保持：`core/types.py` 继续 stdlib-only（dataclass + asdict），
    不引入 pydantic，保留"零依赖泄漏"哲学。
- **P2.1.2 — references/ 知识文档**（2026-04-22）：
  - `skill/solana-security-audit-skill/references/vulnerability-patterns.md`
    从 112 行扩写到 611 行：7 条 Solana 规则每条 ≥ 54 行，含定义 /
    影响 / Detection signals / Kill Signals / Bad vs Good 代码对比 /
    Anchor + Native 变体 / 真实案例 + 上游 Sealevel-Attacks 回链；
    补充"通用根因模式 A/B/C"（从上游 DeFi bug-class 迁移到 Solana
    语境）、"Severity 降级触发器"、"规则优先级"、"上游 Bug-Class
    桥接"三张表。
  - `skill/solana-security-audit-skill/references/report-templates.md`
    从 103 行扩写到 476 行：确立 `risk_summary.md` / `assessment.md`
    / `checklist.md` / `report.json` 四份产出；`assessment.md`
    复用上游 14 节骨架但全部替换为 Solana 小节（Authority 矩阵 /
    Token-2022 扩展 / PDA 一致性 / 兄弟指令一致性 / cargo audit），
    checklist ≥ 17 项分五组；明确 DEGRADED Mode 下各文件的退化行为。
  - `skill/solana-security-audit-skill/references/best-practices.md`
    从 31 行扩写到 155 行、10 条扩充到 20 条（BP-01…BP-20），按
    身份 / 生命周期 / 算术 / 资金 / 依赖 / 可观测性 6 个主题分组，
    并给出"规则 ↔ BP"快速对照表。
  - 所有 references/ 文档之间的相对链接（workflow / patterns /
    templates / best-practices / SKILL.md / LICENSE-THIRD-PARTY.md）
    均可跳转，通过 Python 脚本批量验证。
  - `LICENSE-THIRD-PARTY.md` Attribution table 新增 3 行：
    `vulnerability-patterns.md`（MIT + Sealevel-Attacks Apache-2.0
    复用）、`report-templates.md`（上游 14 节骨架 MIT）、
    `best-practices.md`（上游分组体例 MIT）。
- **P2.1.1 — Skill 目录 + SKILL.md 重写**（2026-04-22）：
  - `skill/solana-security-audit-skill/SKILL.md` 从 158 行扩写到 358 行，
    按 "Do / Input / Output / Tools" 四要素重写 7 步 SOP，加入 Solana
    Authority 风险矩阵、Token-2022 扩展红旗清单、攻击者 10 问短版、
    D/C/B/A/S 评分刻度、降级 (bytecode-only) 处理、端到端 3 个调用示例。
  - `skill/solana-security-audit-skill/references/workflow.md` 从 56 行
    扩写到 401 行，详尽展开每一步：program vs mint 地址识别、Token-2022
    扩展字段提取、规则契约、攻击者 10 问完整表、兄弟函数一致性审查、
    6 步攻击场景建模、Kill-Signal 7 问决策门、评分公式、Callback 重试、
    上游章节映射。
  - `LICENSE-THIRD-PARTY.md`：新增 Attribution table，明确标注
    `SKILL.md` / `workflow.md` 中复用的 `Contract_Security_Audit_Skill`
    上游 SOP 条目（MIT），并内联上游 MIT licence 文本以满足 NOTICE 要求。
- **Python toolchain pinned to [uv](https://docs.astral.sh/uv/)** as a hard
  project-wide constraint. Pip / poetry / conda are no longer supported as
  primary workflows.
- `skill/solana-security-audit-skill/.python-version` — pins Python 3.11.
- `skill/solana-security-audit-skill/uv.lock` — authoritative dependency
  lockfile (committed).
- `skill/solana-security-audit-skill/README.md` — dedicated uv workflow
  reference (install, sync, run, add, export).
- `skill/solana-security-audit-skill/pyproject.toml` gained `[tool.uv]`,
  `[build-system]`, `[dependency-groups]` and optional `test` / `parser`
  extras, plus explicit runtime dependencies.
- `NOTICE` and `LICENSE-THIRD-PARTY.md` — formal MIT + upstream licence attribution.
- SPDX identifier (`SPDX-License-Identifier: MIT`) block in both READMEs.

### Changed
- `scripts/setup.sh` now hard-fails if `uv` is missing and drives the Python
  bootstrap exclusively through `uv sync --extra test`. `python -m venv`
  + `pip install` code paths removed.
- `scripts/verify-phase1.sh` now checks for `uv`, presence of
  `pyproject.toml` / `.python-version` / `uv.lock`, and runs
  `uv run pytest` (fallback to bare interpreter only with a warning).
- `skill/.../requirements.txt` demoted to a pip-compatible fallback; the
  authoritative source is `pyproject.toml` + `uv.lock`. Regenerate via
  `uv export`.
- Project-management docs updated to codify the uv constraint:
  - `docs/04-SolGuard项目管理/00-项目管理总览.md` (§7.2 key constraints).
  - `docs/04-SolGuard项目管理/02-Phase1-环境搭建与学习.md` (P1.1.1 / P1.1.2 / P1.3.1 / P1.3.2 + FAQ).
  - `docs/04-SolGuard项目管理/03-Phase2-Skill与工具开发.md` (tree-sitter via `uv sync --extra parser`).
  - `docs/04-SolGuard项目管理/06-Phase5-集成与联调.md` (Dockerfile uses the `ghcr.io/astral-sh/uv` multi-stage pattern).
  - `docs/04-SolGuard项目管理/10-风险登记册与应急预案.md` (new **R13** — uv unavailability, 🟡).
  - `docs/04-SolGuard项目管理/11-质量保证与验收计划.md` (regression script, Go/No-Go checklist).
- Both READMEs gained a "Dependency management cheatsheet (Python)" section
  plus explicit uv prerequisites.
- README License section expanded with explicit usage terms and pointers
  to NOTICE / LICENSE-THIRD-PARTY.

### Already in place
- `LICENSE` — full MIT text (© 2026 SolGuard Contributors).
- `solguard-server/package.json` — `"license": "MIT"`.
- `skill/solana-security-audit-skill/pyproject.toml` — `license = { text = "MIT" }`.
- MIT shields badge in README.

---
- Initial project scaffold (Phase 1)
- Repository layout: `solguard-server/`, `skill/`, `test-fixtures/`, `scripts/`, `docs/`
- Root config: `.gitignore`, `.env.example`, `.editorconfig`, `LICENSE` (MIT)
- Bilingual README (EN + zh-CN)
- Express + TypeScript backend scaffold with health check, task store, Zod validation
- OpenHarness Skill scaffold with 7-step audit SOP (`SKILL.md`)
- Python skill types, base rule registry, and placeholder modules for parse/scan/ai/report
- 5 seed test-fixture contracts (1 clean + 4 vulnerable)
- Vulnerability patterns + report templates + best practices references
- Phase 1 verification script (`scripts/verify-phase1.sh`)
- One-shot setup script (`scripts/setup.sh`)

[Unreleased]: https://github.com/Keybird0/SolGuard/compare/HEAD...HEAD
