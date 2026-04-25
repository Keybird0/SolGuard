// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { describe, it } from 'node:test';
import { runPython } from './python-runner';
import type { AgentEvent, NormalizedInput } from '../types';

type SpawnLike = typeof import('node:child_process').spawn;

interface FakeChild extends EventEmitter {
  stdout: Readable;
  stderr: Readable;
  killed: boolean;
  kill(signal?: string): boolean;
}

function makeChild(
  stdoutChunks: string[],
  stderrChunks: string[] = [],
  exitCode = 0,
  delayMs = 5,
): FakeChild {
  const emitter = new EventEmitter() as FakeChild;
  emitter.stdout = Readable.from(stdoutChunks);
  emitter.stderr = Readable.from(stderrChunks);
  emitter.killed = false;
  emitter.kill = () => {
    emitter.killed = true;
    return true;
  };
  setTimeout(() => emitter.emit('close', exitCode), delayMs);
  return emitter;
}

const NORMALIZED: NormalizedInput[] = [
  {
    kind: 'rust_source',
    rootDir: '/tmp/fake-root',
    primaryFile: '/tmp/fake-root/lib.rs',
    origin: { type: 'github', value: 'https://example.com/foo/bar' },
  },
];

describe('runPython', () => {
  it('parses stage events and maps them to tool names', async () => {
    const events: AgentEvent[] = [];
    const stdout = [
      '{"stage":"parse","file":"lib.rs"}\n',
      '{"stage":"scan"}\n',
      '{"stage":"semgrep"}\n',
      '{"stage":"ai_analyze","provider":"anthropic"}\n',
      '{"stage":"report"}\n',
      '[solguard] task=t1 output=/tmp/out/t1\n',
    ];

    const spawnFn: SpawnLike = ((_cmd: string, _args: string[]) =>
      makeChild(stdout)) as unknown as SpawnLike;

    const result = await runPython({
      taskId: 't1',
      normalizedInputs: NORMALIZED,
      callbackUrl: 'http://localhost:3000/api/audit/t1/complete',
      callbackToken: 'test-token',
      forceDegraded: true,
      onEvent: (e) => events.push(e),
      spawnFn,
    });

    assert.equal(result.exitCode, 0);
    assert.equal(result.timedOut, false);
    const tools = events
      .filter((e) => e.type === 'tool_call_start')
      .map((e) => e.tool);
    assert.deepEqual(tools, [
      'solana_parse',
      'solana_scan',
      'solana_semgrep',
      'solana_ai_analyze',
      'solana_report',
    ]);
  });

  it('surfaces non-zero exit code and stderr tail', async () => {
    const stderr = ['Traceback (most recent call last):\n  …\nRuntimeError: boom\n'];
    const spawnFn: SpawnLike = ((_cmd: string, _args: string[]) =>
      makeChild([], stderr, 3)) as unknown as SpawnLike;

    const result = await runPython({
      taskId: 't2',
      normalizedInputs: NORMALIZED,
      callbackUrl: 'http://localhost:3000/api/audit/t2/complete',
      callbackToken: 'test-token',
      spawnFn,
    });

    assert.equal(result.exitCode, 3);
    assert.match(result.stderr, /RuntimeError: boom/);
  });

  it('tolerates non-JSON log lines interleaved with stage events', async () => {
    const stdout = [
      '[python] warming caches\n',
      '{"stage":"parse"}\n',
      '[python] done\n',
      '{"stage":"report"}\n',
    ];
    const spawnFn: SpawnLike = ((_cmd: string, _args: string[]) =>
      makeChild(stdout, [], 0)) as unknown as SpawnLike;

    const events: AgentEvent[] = [];
    const result = await runPython({
      taskId: 't3',
      normalizedInputs: NORMALIZED,
      callbackUrl: 'http://localhost:3000/api/audit/t3/complete',
      callbackToken: 'test-token',
      onEvent: (e) => events.push(e),
      spawnFn,
    });

    assert.equal(result.exitCode, 0);
    const toolEvents = events.filter((e) => e.type === 'tool_call_start');
    assert.equal(toolEvents.length, 2);
    assert.deepEqual(toolEvents.map((e) => e.tool), ['solana_parse', 'solana_report']);
  });

  it('times out and kills the process when child hangs', async () => {
    const emitter = new EventEmitter() as FakeChild;
    emitter.stdout = new Readable({ read() {} });
    emitter.stderr = new Readable({ read() {} });
    emitter.killed = false;
    emitter.kill = () => {
      emitter.killed = true;
      setTimeout(() => emitter.emit('close', null), 5);
      return true;
    };
    const spawnFn: SpawnLike = ((_cmd: string, _args: string[]) =>
      emitter) as unknown as SpawnLike;

    const result = await runPython({
      taskId: 't4',
      normalizedInputs: NORMALIZED,
      callbackUrl: 'http://localhost:3000/api/audit/t4/complete',
      callbackToken: 'test-token',
      timeoutMs: 30,
      spawnFn,
    });

    assert.equal(result.timedOut, true);
    assert.equal(emitter.killed, true);
  });
});
