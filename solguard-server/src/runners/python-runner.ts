// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// python-runner.ts — fallback runner that drives the SolGuard skill via
// `uv run python scripts/run_audit.py` when the OpenHarness CLI is
// unavailable (not installed, failed, or disabled via FREE_AUDIT /
// RUNNER_FALLBACK_TO_PYTHON). Emits the same AgentResult shape as
// runAgent() so audit-engine.ts can swap runners transparently.
//
// stdout contract (matches run_audit.py --emit-events):
//   {"stage": "parse" | "scan" | "semgrep" | "ai_analyze" | "report", ...}
// plus human-readable tail lines "[solguard] task=... output=..." etc.
//
// The HTTP callback is sent by run_audit.py itself (via --callback-url),
// so this runner only needs to (a) map stage events to AgentEvent tool
// events so audit-engine's status machine advances, and (b) surface
// exit codes / stderr for logging.
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { config } from '../config';
import { logger } from '../logger';
import type { AgentEvent, NormalizedInput } from '../types';
import type { AgentResult } from '../openharness-client';

export interface PythonRunOptions {
  taskId: string;
  normalizedInputs: NormalizedInput[];
  outputRoot?: string;
  callbackUrl: string;
  callbackToken: string;
  forceDegraded?: boolean;
  timeoutMs?: number;
  onEvent?: (event: AgentEvent) => void;
  onStderr?: (chunk: string) => void;
  spawnFn?: typeof spawn;
  pythonBin?: string;
  scriptPath?: string;
  inputsJsonPath?: string;
  env?: NodeJS.ProcessEnv;
}

const STAGE_TO_TOOL: Record<string, string> = {
  parse: 'solana_parse',
  scan: 'solana_scan',
  semgrep: 'solana_semgrep',
  ai_analyze: 'solana_ai_analyze',
  report: 'solana_report',
};

function parseStageLine(raw: string): AgentEvent | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (!trimmed.startsWith('{')) {
    return { type: 'unknown', raw: trimmed };
  }
  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;
    const stage = typeof obj.stage === 'string' ? obj.stage : undefined;
    if (!stage) {
      return { type: 'unknown', data: obj, raw: trimmed };
    }
    const tool = STAGE_TO_TOOL[stage] ?? `solana_${stage}`;
    return {
      type: 'tool_call_start',
      tool,
      data: obj,
      raw: trimmed,
    };
  } catch {
    return { type: 'unknown', raw: trimmed };
  }
}

function splitLines(buffer: string): { lines: string[]; rest: string } {
  const parts = buffer.split(/\r?\n/);
  const rest = parts.pop() ?? '';
  return { lines: parts, rest };
}

function writeInputsJson(taskId: string, inputs: NormalizedInput[]): string {
  const dir = path.resolve(tmpdir(), 'solguard-runner');
  mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, `${taskId}.inputs.json`);
  writeFileSync(filePath, JSON.stringify(inputs, null, 2), 'utf-8');
  return filePath;
}

function resolveScriptPath(rawPath: string): string {
  if (path.isAbsolute(rawPath)) return rawPath;

  const serverRoot = path.resolve(__dirname, '..', '..');
  const repoRoot = path.resolve(serverRoot, '..');
  const candidates = [
    path.resolve(process.cwd(), rawPath),
    path.resolve(serverRoot, rawPath),
    path.resolve(repoRoot, rawPath),
  ];

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  // Preserve Node's normal relative-path behavior in the error message if no
  // candidate exists; the caller will surface the failed path in stderr.
  return candidates[0] as string;
}

function readFinalResultFromReport(outputRoot: string, taskId: string): unknown {
  const taskOutputDir = path.resolve(outputRoot, taskId);
  const reportJsonPath = path.join(taskOutputDir, 'report.json');
  try {
    const report = JSON.parse(readFileSync(reportJsonPath, 'utf-8')) as Record<string, unknown>;
    const stats = (report.statistics ?? {}) as Record<string, unknown>;
    const rawFindings = Array.isArray(report.findings) ? report.findings : [];
    const findings = rawFindings.map((item, idx) => {
      const finding = item as Record<string, unknown>;
      return {
        id: String(finding.id ?? `F-${String(idx).padStart(3, '0')}`),
        ruleId: typeof finding.rule_id === 'string' ? finding.rule_id : undefined,
        severity: String(finding.severity ?? 'Medium'),
        title: String(finding.title ?? 'finding'),
        location: String(finding.location ?? ''),
        description: String(finding.description ?? ''),
        impact: String(finding.impact ?? ''),
        recommendation: String(finding.recommendation ?? ''),
        codeSnippet:
          typeof finding.code_snippet === 'string' ? finding.code_snippet : undefined,
        confidence:
          typeof finding.confidence === 'number' ? finding.confidence : undefined,
      };
    });

    const reports = (report.reports ?? {}) as Record<string, unknown>;
    const assessmentPath =
      typeof reports.assessment === 'string'
        ? reports.assessment
        : path.join(taskOutputDir, 'assessment.md');
    const reportMarkdown = existsSync(assessmentPath)
      ? readFileSync(assessmentPath, 'utf-8')
      : '';

    return {
      status: 'completed',
      statistics: {
        critical: Number(stats.critical ?? 0),
        high: Number(stats.high ?? 0),
        medium: Number(stats.medium ?? 0),
        low: Number(stats.low ?? 0),
        info: Number(stats.info ?? 0),
        total: Number(stats.total ?? rawFindings.length),
      },
      findings,
      reportMarkdown,
    };
  } catch (err) {
    logger.warn({ err, taskId, reportJsonPath }, 'failed to read python report fallback');
    return undefined;
  }
}

export async function runPython(opts: PythonRunOptions): Promise<AgentResult> {
  const spawnFn = opts.spawnFn ?? spawn;
  const pythonBin = opts.pythonBin ?? config.pythonBin;
  const scriptPath = resolveScriptPath(opts.scriptPath ?? config.pythonRunAuditScript);
  const skillRoot = path.resolve(path.dirname(scriptPath), '..');
  const timeoutMs = opts.timeoutMs ?? config.agentTimeoutMs;
  const outputRoot = opts.outputRoot ?? config.auditOutputRoot;

  const inputsJsonPath =
    opts.inputsJsonPath ?? writeInputsJson(opts.taskId, opts.normalizedInputs);

  const scriptArgs =
    pythonBin === 'uv'
      ? ['run', 'python', scriptPath]
      : [scriptPath];

  const args = [
    ...scriptArgs,
    '--inputs-json',
    inputsJsonPath,
    '--task-id',
    opts.taskId,
    '--output-root',
    outputRoot,
    '--emit-events',
    '--callback-url',
    opts.callbackUrl,
    '--callback-token',
    opts.callbackToken,
  ];

  if (opts.forceDegraded) args.push('--degraded');

  logger.debug(
    { taskId: opts.taskId, pythonBin, scriptPath, timeoutMs },
    'spawning python fallback runner',
  );

  return new Promise<AgentResult>((resolve) => {
    let child: ChildProcess;
    try {
      child = spawnFn(pythonBin, args, {
        cwd: skillRoot,
        env: { ...process.env, ...opts.env },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      logger.error({ err: msg, taskId: opts.taskId }, 'python spawn threw');
      resolve({
        exitCode: -1,
        stdout: '',
        stderr: msg,
        events: [{ type: 'error', raw: msg }],
        timedOut: false,
      });
      return;
    }

    const events: AgentEvent[] = [];
    let stdoutBuf = '';
    let stderrBuf = '';
    let pendingLine = '';
    let finalResult: unknown;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      logger.warn({ taskId: opts.taskId, timeoutMs }, 'python runner timed out, killing');
      child.kill('SIGTERM');
      setTimeout(() => {
        if (!child.killed) child.kill('SIGKILL');
      }, 2000).unref?.();
    }, timeoutMs);
    timer.unref?.();

    child.stdout?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      stdoutBuf += text;
      const { lines, rest } = splitLines(pendingLine + text);
      pendingLine = rest;
      for (const line of lines) {
        const evt = parseStageLine(line);
        if (!evt) continue;
        events.push(evt);
        try {
          opts.onEvent?.(evt);
        } catch (err) {
          logger.error({ err }, 'onEvent threw');
        }
      }
    });

    child.stderr?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8');
      stderrBuf += text;
      try {
        opts.onStderr?.(text);
      } catch (err) {
        logger.error({ err }, 'onStderr threw');
      }
    });

    child.on('error', (err) => {
      logger.error({ err: err.message, taskId: opts.taskId }, 'python process error');
      events.push({ type: 'error', raw: err.message });
    });

    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0 && !finalResult) {
        finalResult = readFinalResultFromReport(outputRoot, opts.taskId);
      }
      resolve({
        exitCode: code,
        stdout: stdoutBuf,
        stderr: stderrBuf,
        events,
        finalResult,
        timedOut,
      });
    });
  });
}
