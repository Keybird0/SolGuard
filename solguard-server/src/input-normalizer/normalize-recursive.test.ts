// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { describe, it } from 'node:test';
import { normalize, normalizeAll } from './index';

type SpawnLike = typeof import('node:child_process').spawn;

function fakeSpawn(): SpawnLike {
  return ((_cmd: string, args: string[]) => {
    const emitter = new EventEmitter() as EventEmitter & {
      stdout: Readable;
      stderr: Readable;
      killed: boolean;
      kill(): boolean;
    };
    emitter.stdout = Readable.from([]);
    emitter.stderr = Readable.from([]);
    emitter.killed = false;
    emitter.kill = () => {
      emitter.killed = true;
      return true;
    };
    const target = args[args.length - 1];
    mkdirSync(path.join(target, 'src'), { recursive: true });
    writeFileSync(path.join(target, 'src', 'lib.rs'), 'fn main() {}');
    setTimeout(() => emitter.emit('close', 0), 5);
    return emitter;
  }) as unknown as SpawnLike;
}

function mockFetch(body: string): typeof fetch {
  return (async () =>
    ({
      status: 200,
      ok: true,
      text: async () => body,
      headers: new Headers(),
    }) as unknown as Response) as typeof fetch;
}

describe('normalize (recursion)', () => {
  it('website → github lead → rust_source (2-level recursion)', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-rec-'));
    const res = await normalize(
      { type: 'website', value: 'https://example.com' },
      workdir,
      {
        github: { spawnFn: fakeSpawn(), gitBin: 'git-mock' },
        url: { fetchImpl: mockFetch('visit https://github.com/alpha/beta for source') },
        maxRecursionDepth: 2,
      },
    );
    assert.equal(res.kind, 'rust_source');
    if (res.kind === 'rust_source') {
      assert.equal(res.origin.type, 'github');
      assert.equal(res.origin.value, 'https://github.com/alpha/beta');
    }
  });

  it('bails out after maxRecursionDepth', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-rec-'));
    // website keeps pointing to itself → infinite loop without a cap
    const selfLoopHtml = 'see https://github.com/a/b for details';
    // use a URL extractor that returns another website, forcing
    // website → website → website chain.
    let hits = 0;
    await assert.rejects(
      normalize(
        { type: 'website', value: 'https://one.example.com' },
        workdir,
        {
          url: {
            fetchImpl: mockFetch(selfLoopHtml),
            llmExtractor: async () => {
              hits++;
              return [{ type: 'website', value: `https://n${hits}.example.com` }];
            },
          },
          maxRecursionDepth: 1,
        },
      ),
      /recursion limit/,
    );
  });
});

describe('normalizeAll', () => {
  it('collects errors without failing the whole batch', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-batch-'));
    const { normalized, errors } = await normalizeAll(
      [
        { type: 'github', value: 'https://gitlab.com/foo/bar' },
        { type: 'website', value: 'https://example.com' },
      ],
      workdir,
      {
        url: { fetchImpl: mockFetch('no leads here') },
      },
    );
    assert.equal(normalized.length, 1);
    assert.equal(errors.length, 1);
    assert.match(errors[0], /not a github\.com URL/);
    assert.equal(normalized[0].kind, 'lead_only');
  });
});
