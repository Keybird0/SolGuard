// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { describe, it } from 'node:test';
import { runAgent } from './openharness-client';
import type { AgentEvent } from './types';

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
  delayMs = 10,
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

describe('openharness-client.runAgent', () => {
  it('parses json-stream events and final result', async () => {
    const events: AgentEvent[] = [];
    const stdout = [
      JSON.stringify({ type: 'tool_call_start', tool: 'solana_parse' }) + '\n',
      JSON.stringify({ type: 'tool_call_end', tool: 'solana_parse' }) + '\n',
      JSON.stringify({
        type: 'final_result',
        data: { statistics: { critical: 0, total: 1 } },
      }) + '\n',
    ];
    const fakeSpawn: SpawnLike = (() => makeChild(stdout)) as unknown as SpawnLike;

    const result = await runAgent({
      prompt: 'hello',
      taskId: 't1',
      spawnFn: fakeSpawn,
      onEvent: (e) => events.push(e),
      outputFormat: 'json-stream',
      timeoutMs: 5000,
    });

    assert.equal(result.exitCode, 0);
    assert.equal(result.timedOut, false);
    assert.ok(events.some((e) => e.tool === 'solana_parse' && e.type === 'tool_call_start'));
    assert.ok(events.some((e) => e.type === 'final_result'));
    assert.ok(result.finalResult);
  });

  it('falls back to parsing full json when format is json', async () => {
    const payload = JSON.stringify({ status: 'completed', statistics: { total: 3 } });
    const fakeSpawn: SpawnLike = (() =>
      makeChild([payload])) as unknown as SpawnLike;

    const result = await runAgent({
      prompt: 'hello',
      taskId: 't2',
      spawnFn: fakeSpawn,
      outputFormat: 'json',
      timeoutMs: 5000,
    });

    assert.equal(result.exitCode, 0);
    assert.deepEqual(result.finalResult, { status: 'completed', statistics: { total: 3 } });
  });

  it('times out and kills the process', async () => {
    const fakeChild = (() => {
      const emitter = new EventEmitter() as FakeChild;
      emitter.stdout = Readable.from([]);
      emitter.stderr = Readable.from([]);
      emitter.killed = false;
      emitter.kill = (_sig?: string) => {
        emitter.killed = true;
        setTimeout(() => emitter.emit('close', null), 5);
        return true;
      };
      return emitter;
    }) as unknown as SpawnLike;

    const result = await runAgent({
      prompt: 'slow',
      taskId: 't3',
      spawnFn: fakeChild,
      timeoutMs: 50,
      outputFormat: 'json-stream',
    });

    assert.equal(result.timedOut, true);
  });
});
