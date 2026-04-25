// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { createWriteStream, mkdirSync, type WriteStream } from 'node:fs';
import path from 'node:path';
import { config } from './config';
import { enqueueAuditEmail } from './email';
import { logger } from './logger';
import {
  notifyScanCompleted,
  notifyScanFailed,
} from './notify/lark';
import {
  runAgent,
  checkCliAvailable,
  type AgentRunOptions,
  type AgentResult,
} from './openharness-client';
import { runPython, type PythonRunOptions } from './runners/python-runner';
import { getTaskStore, type TaskStore } from './storage/task-store';
import type {
  AgentEvent,
  AuditInput,
  AuditTask,
  TaskStatus,
} from './types';

function formatInputs(inputs: AuditInput[]): string {
  return inputs
    .filter((inp) => inp.type !== 'more_info')
    .map((inp, i) => `  ${i + 1}. [${inp.type}] ${inp.value}`)
    .join('\n');
}

/**
 * Collect user-supplied free-form context ("More Info" fields). Rendered as a
 * separate section of the prompt so the LLM treats it as unverified context
 * rather than an input the scanners should try to normalize.
 */
function formatMoreInfo(inputs: AuditInput[]): string {
  const blocks = inputs
    .filter((inp) => inp.type === 'more_info' && inp.value.trim())
    .map((inp, i) => `### Note ${i + 1}\n${inp.value.trim()}`);
  return blocks.join('\n\n');
}

function formatNormalizedInputs(task: AuditTask): string {
  if (!task.normalizedInputs || task.normalizedInputs.length === 0) {
    return '(无规整后输入；Agent 将按原始 inputs 降级处理)';
  }
  return task.normalizedInputs
    .map((n, i) => {
      if (n.kind === 'rust_source') {
        return `  ${i + 1}. [rust_source] rootDir=${n.rootDir}${n.primaryFile ? ` primary=${n.primaryFile}` : ''} (origin: ${n.origin.type}=${n.origin.value})`;
      }
      if (n.kind === 'bytecode_only') {
        return `  ${i + 1}. [bytecode_only] programId=${n.programId} bytecode=${n.bytecodePath} (origin: ${n.origin.type}=${n.origin.value}) — DEGRADED`;
      }
      return `  ${i + 1}. [lead_only] leads=${n.leadsJsonPath} (origin: ${n.origin.type}=${n.origin.value}) — DEGRADED`;
    })
    .join('\n');
}

export function buildAuditPrompt(task: AuditTask): string {
  const skillDir = config.ohSkillDir ?? '~/.openharness/skills/solana-security-audit-skill';
  const workdir = path.resolve(config.auditWorkdir, task.taskId);
  const callbackUrl = `${config.publicBaseUrl}/api/audit/${task.taskId}/complete`;
  const outputRoot = path.resolve(config.auditOutputRoot ?? 'outputs', task.taskId);

  const moreInfoBlock = formatMoreInfo(task.inputs);

  return `使用 solana-security-audit-skill 对以下 Solana 项目输入进行安全审计：

## 原始输入
${formatInputs(task.inputs)}

## 后端预规整结果（已完成输入归一化，source 字段可直接消费）
${formatNormalizedInputs(task)}
${
  moreInfoBlock
    ? `

## Additional Context (user-provided)
以下内容是提交者提供的自由文本说明，作为审计背景参考。请在交叉验证阶段纳入考虑；**不要**对其中的 URL 做抓取，也**不要**把它当作源码扫描对象。

${moreInfoBlock}`
    : ''
}

## 执行要求

严格按照 ${skillDir}/SKILL.md 的 6 步 AI-first 工作流执行，所有 LLM 分析必须通过 solana_ai_analyze 工具；**不要**自行正则解析源码、**不要**直接调用 LLM。
工作目录: ${workdir}
报告输出: ${outputRoot}

依次调用以下 5 个工具（严格顺序 / 跳步即失败）：
1. solana_parse        — 解析每个 rust_source 的 Rust / Anchor 结构
2. solana_scan         — 产出 7 条规则的 hints（confidence=low，待 AI 裁判）
3. solana_semgrep      — 运行 Solana Semgrep 规则，原始 JSON 直喂 AI
4. solana_ai_analyze   — 一次调用完成「交叉验证 scan/semgrep hints」+「探索式补漏」（对应
                          AIAnalyzer.cross_validate_and_explore，内含 Kill-Signal 验证；
                          temperature ≤ 0.1，JSON mode）
5. solana_report       — 按 AI 产出的 Markdown 三段落盘 + sha256 + report.json

对 normalizedInputs[].kind != rust_source 的条目，跳过 parse/scan/semgrep 直接交 solana_ai_analyze 处理 DEGRADED 路径；solana_report 在 scan_result.decision=degraded 时仍出 risk_summary.md，顶部写入 "DEGRADED — LLM unavailable" 或 "DEGRADED — source unavailable"。

## 完成动作

生成报告后，通过 HTTP POST 将结果回调到审计服务：

URL: ${callbackUrl}
Headers:
  Content-Type: application/json
  X-Agent-Token: ${config.agentCallbackToken}

Body:
\`\`\`json
{
  "status": "completed",
  "statistics": {
    "critical": <num>, "high": <num>, "medium": <num>, "low": <num>, "info": <num>, "total": <num>
  },
  "findings": [
    {
      "id": "F-001",
      "ruleId": "missing_signer_check",
      "severity": "Critical|High|Medium|Low|Info",
      "title": "...",
      "location": "file:line",
      "description": "...",
      "impact": "...",
      "recommendation": "..."
    }
  ],
  "reportMarkdown": "<完整 Markdown 报告内容>",
  "reportUrl": "<可选：在线报告链接>"
}
\`\`\`

审计失败时回调：
\`\`\`json
{ "status": "failed", "error": "<原因摘要>" }
\`\`\`

请按以上顺序执行并确保在任务结束前完成 HTTP 回调。`;
}

const TOOL_STATUS_MAP: Record<string, { status: TaskStatus; progress: string; percent: number }> = {
  solana_parse: { status: 'scanning', progress: 'Parsing Rust / Anchor AST...', percent: 25 },
  solana_scan: { status: 'scanning', progress: 'Running rule scanner...', percent: 40 },
  solana_semgrep: { status: 'scanning', progress: 'Running semgrep rules...', percent: 55 },
  solana_ai_analyze: { status: 'analyzing', progress: 'AI cross-validation + exploration...', percent: 75 },
  solana_report: { status: 'reporting', progress: 'Composing report...', percent: 95 },
};

const STATUS_ORDER: Record<TaskStatus, number> = {
  pending: 0,
  paying: 1,
  paid: 2,
  scanning: 3,
  analyzing: 4,
  reporting: 5,
  completed: 6,
  failed: 6,
};

export interface AuditEngineDeps {
  store?: TaskStore;
  runner?: (opts: AgentRunOptions) => ReturnType<typeof runAgent>;
  pythonRunner?: (opts: PythonRunOptions) => Promise<AgentResult>;
  cliAvailableCheck?: () => Promise<boolean>;
  fetchImpl?: typeof fetch;
}

export interface AuditEngine {
  enqueue(taskId: string): Promise<void>;
  onAuditFinished(task: AuditTask): Promise<void>;
}

class DefaultAuditEngine implements AuditEngine {
  private readonly store: TaskStore;
  private readonly runner: (opts: AgentRunOptions) => ReturnType<typeof runAgent>;
  private readonly pythonRunner: (opts: PythonRunOptions) => Promise<AgentResult>;
  private readonly cliAvailableCheck: () => Promise<boolean>;
  private readonly fetchImpl: typeof fetch;
  private readonly inFlight = new Set<string>();

  constructor(deps: AuditEngineDeps = {}) {
    this.store = deps.store ?? getTaskStore();
    this.runner = deps.runner ?? runAgent;
    this.pythonRunner = deps.pythonRunner ?? runPython;
    this.cliAvailableCheck = deps.cliAvailableCheck ?? (() => checkCliAvailable());
    this.fetchImpl = deps.fetchImpl ?? fetch;
  }

  async enqueue(taskId: string): Promise<void> {
    if (this.inFlight.has(taskId)) {
      logger.warn({ taskId }, 'audit already in flight, ignoring duplicate enqueue');
      return;
    }
    this.inFlight.add(taskId);
    try {
      await this.execute(taskId);
    } finally {
      this.inFlight.delete(taskId);
    }
  }

  private async execute(taskId: string): Promise<void> {
    const task = await this.store.get(taskId);
    if (!task) {
      logger.error({ taskId }, 'execute: task not found');
      return;
    }

    await this.store.update(taskId, {
      status: 'scanning',
      progress: 'Dispatching to OpenHarness agent...',
      progressPercent: 5,
    });

    const prompt = buildAuditPrompt(task);
    const logStream = this.openLogStream(taskId);

    const onEvent = (evt: AgentEvent): void => {
      this.mapEventToStatus(taskId, evt).catch((err) => {
        logger.error({ err, taskId }, 'mapEventToStatus failed');
      });
    };
    const onStderr = (chunk: string): void => {
      logStream?.write(chunk);
    };

    // Decide OH vs Python path. Python is preferred when:
    //   - config.freeAudit is true (no payment, no LLM → skip Agent loop), OR
    //   - config.runnerFallbackToPython AND `oh` binary is not resolvable.
    let ohAvailable = true;
    if (config.runnerFallbackToPython) {
      try {
        ohAvailable = await this.cliAvailableCheck();
      } catch (err) {
        logger.warn({ err, taskId }, 'cliAvailableCheck threw; assuming oh unavailable');
        ohAvailable = false;
      }
    }

    const preferPython =
      config.freeAudit ||
      (config.runnerFallbackToPython && !ohAvailable);

    const MAX_ATTEMPTS = 2;
    let lastError: string | undefined;
    let lastErrorKind: 'oh_unavailable' | 'oh_timeout' | 'oh_nonzero' | 'python_failed' | undefined;

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const usePython = preferPython || attempt === MAX_ATTEMPTS && lastErrorKind !== undefined;
      try {
        const result = usePython
          ? await this.runPythonPath(task, { onEvent, onStderr })
          : await this.runner({ prompt, taskId, onEvent, onStderr });

        if (result.timedOut) {
          lastError = `Runner timed out after ${config.agentTimeoutMs} ms`;
          lastErrorKind = usePython ? 'python_failed' : 'oh_timeout';
        } else if (result.exitCode === 0) {
          const current = await this.store.get(taskId);
          if (current && current.status !== 'completed' && current.status !== 'failed') {
            const applied = await this.fallbackCallback(taskId, result.finalResult);
            if (!applied) {
              lastError = 'Agent exited without producing a final result';
              lastErrorKind = usePython ? 'python_failed' : 'oh_nonzero';
            } else {
              logStream?.end();
              return;
            }
          } else {
            logStream?.end();
            return;
          }
        } else {
          lastError = `runner exited with code ${result.exitCode}: ${result.stderr.slice(-400)}`;
          lastErrorKind = usePython ? 'python_failed' : 'oh_nonzero';
        }
      } catch (err) {
        lastError = err instanceof Error ? err.message : String(err);
        lastErrorKind = usePython ? 'python_failed' : 'oh_unavailable';
        logger.error({ err, taskId, attempt, usePython }, 'runner threw');
      }

      if (attempt < MAX_ATTEMPTS) {
        const backoff = 2000 * attempt;
        logger.warn(
          { taskId, attempt, backoff, lastError, lastErrorKind },
          'retrying audit (next attempt may switch to python fallback)',
        );
        await sleep(backoff);
      }
    }

    logStream?.end();
    await this.store.update(taskId, {
      status: 'failed',
      error: lastError ?? 'Agent execution failed',
      completedAt: new Date().toISOString(),
    });
    const failed = await this.store.get(taskId);
    if (failed) {
      await this.onAuditFinished(failed);
    }
  }

  private async runPythonPath(
    task: AuditTask,
    handlers: { onEvent: (e: AgentEvent) => void; onStderr: (c: string) => void },
  ): Promise<AgentResult> {
    const normalized = task.normalizedInputs ?? [];
    if (normalized.length === 0) {
      logger.warn(
        { taskId: task.taskId },
        'python path invoked without normalizedInputs; runner will error out',
      );
    }
    const callbackUrl = `${config.publicBaseUrl}/api/audit/${task.taskId}/complete`;
    // FREE_AUDIT defaults to degraded (no LLM spend). Set
    // DEMO_FORCE_LLM=true to opt back into real LLM calls when a valid
    // provider key is wired — used by local demos and Phase-5 rehearsals.
    const demoForceLlm = (process.env.DEMO_FORCE_LLM ?? '').toLowerCase() === 'true';
    return this.pythonRunner({
      taskId: task.taskId,
      normalizedInputs: normalized,
      outputRoot: path.resolve(config.auditOutputRoot),
      callbackUrl,
      callbackToken: config.agentCallbackToken,
      forceDegraded: config.freeAudit && !demoForceLlm,
      onEvent: handlers.onEvent,
      onStderr: handlers.onStderr,
    });
  }

  private async mapEventToStatus(taskId: string, evt: AgentEvent): Promise<void> {
    if ((evt.type === 'tool_call_start' || evt.type === 'tool_call_end') && evt.tool) {
      const mapping = TOOL_STATUS_MAP[evt.tool];
      if (!mapping) return;
      const current = await this.store.get(taskId);
      if (!current) return;
      if (STATUS_ORDER[mapping.status] < STATUS_ORDER[current.status]) {
        return;
      }
      if (current.status === mapping.status && current.progress === mapping.progress) {
        return;
      }
      await this.store.update(taskId, {
        status: mapping.status,
        progress: mapping.progress,
        progressPercent: mapping.percent,
      });
    }
  }

  private async fallbackCallback(taskId: string, finalResult: unknown): Promise<boolean> {
    logger.info({ taskId }, 'agent exited 0 but no HTTP callback received; using stdout fallback');
    try {
      if (finalResult && typeof finalResult === 'object') {
        const url = `${config.publicBaseUrl}/api/audit/${taskId}/complete`;
        await this.fetchImpl(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Agent-Token': config.agentCallbackToken,
          },
          body: JSON.stringify({ status: 'completed', ...finalResult }),
        });
        return true;
      } else {
        return false;
      }
    } catch (err) {
      logger.error({ err, taskId }, 'fallbackCallback failed');
      return false;
    }
  }

  private openLogStream(taskId: string): WriteStream | null {
    try {
      const dir = path.resolve(config.dataDir, 'logs');
      mkdirSync(dir, { recursive: true });
      const filePath = path.join(dir, `${taskId}.log`);
      return createWriteStream(filePath, { flags: 'a' });
    } catch (err) {
      logger.warn({ err, taskId }, 'failed to open log stream');
      return null;
    }
  }

  async onAuditFinished(task: AuditTask): Promise<void> {
    try {
      await enqueueAuditEmail(task);
    } catch (err) {
      logger.error({ err, taskId: task.taskId }, 'enqueueAuditEmail failed');
    }
    try {
      if (task.status === 'completed') {
        await notifyScanCompleted(task);
      } else if (task.status === 'failed') {
        await notifyScanFailed(task);
      }
    } catch (err) {
      logger.warn({ err, taskId: task.taskId }, 'lark completion notify failed');
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms).unref?.();
  });
}

let singleton: AuditEngine | null = null;

export function getAuditEngine(deps?: AuditEngineDeps): AuditEngine {
  if (!singleton) {
    singleton = new DefaultAuditEngine(deps);
  }
  return singleton;
}

export function setAuditEngineForTesting(engine: AuditEngine | null): void {
  singleton = engine;
}
