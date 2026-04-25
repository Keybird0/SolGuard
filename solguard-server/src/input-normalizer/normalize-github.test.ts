// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { describe, it } from 'node:test';
import { normalizeGithub, findPrimaryRustFile } from './normalize-github';

type SpawnLike = typeof import('node:child_process').spawn;

function makeChild(exitCode = 0, stderrChunks: string[] = [], delayMs = 5) {
  const emitter = new EventEmitter() as EventEmitter & {
    stdout: Readable;
    stderr: Readable;
    killed: boolean;
    kill(): boolean;
  };
  emitter.stdout = Readable.from([]);
  emitter.stderr = Readable.from(stderrChunks);
  emitter.killed = false;
  emitter.kill = () => {
    emitter.killed = true;
    return true;
  };
  setTimeout(() => emitter.emit('close', exitCode), delayMs);
  return emitter;
}

describe('normalizeGithub', () => {
  it('invokes git with depth=1 and returns rust_source', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-github-'));
    let capturedArgs: string[] = [];
    const spawnFn: SpawnLike = ((_cmd: string, args: string[]) => {
      capturedArgs = args;
      // Simulate a successful clone by creating the destination directory tree.
      const target = args[args.length - 1];
      const progSrc = path.join(target, 'programs', 'foo', 'src');
      mkdirSync(progSrc, { recursive: true });
      writeFileSync(path.join(progSrc, 'lib.rs'), 'fn main() {}');
      return makeChild(0);
    }) as unknown as SpawnLike;

    const res = await normalizeGithub(
      { type: 'github', value: 'https://github.com/foo/bar' },
      workdir,
      { spawnFn, gitBin: 'git-mock' },
    );

    assert.equal(res.kind, 'rust_source');
    if (res.kind === 'rust_source') {
      assert.ok(res.rootDir.endsWith('foo-bar'));
      assert.ok(res.primaryFile?.endsWith('programs/foo/src/lib.rs'));
    }
    assert.deepEqual(capturedArgs.slice(0, 3), ['clone', '--depth=1', '--single-branch']);
  });

  it('rejects non-github urls', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-github-'));
    await assert.rejects(
      normalizeGithub(
        { type: 'github', value: 'https://gitlab.com/foo/bar' },
        workdir,
        {},
      ),
      /not a github\.com URL/,
    );
  });

  it('strips /tree/branch path and re-uses cached clone', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-github-'));
    let cloneCalls = 0;
    const spawnFn: SpawnLike = ((_cmd: string, args: string[]) => {
      cloneCalls++;
      const target = args[args.length - 1];
      mkdirSync(path.join(target, 'src'), { recursive: true });
      writeFileSync(path.join(target, 'src', 'lib.rs'), 'fn x() {}');
      return makeChild(0);
    }) as unknown as SpawnLike;

    const first = await normalizeGithub(
      { type: 'github', value: 'https://github.com/foo/bar/tree/main/examples' },
      workdir,
      { spawnFn },
    );
    const second = await normalizeGithub(
      { type: 'github', value: 'https://github.com/foo/bar' },
      workdir,
      { spawnFn },
    );

    assert.equal(cloneCalls, 1, 'second call should reuse cache');
    if (first.kind === 'rust_source' && second.kind === 'rust_source') {
      assert.equal(first.rootDir, second.rootDir);
    }
  });
});

describe('findPrimaryRustFile', () => {
  it('prefers Anchor programs/*/src/lib.rs', () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-findrs-'));
    const prog = path.join(workdir, 'programs', 'p1', 'src');
    mkdirSync(prog, { recursive: true });
    writeFileSync(path.join(prog, 'lib.rs'), '');
    const tests = path.join(workdir, 'tests');
    mkdirSync(tests);
    writeFileSync(path.join(tests, 'a.rs'), '');
    const found = findPrimaryRustFile(workdir);
    assert.ok(found && found.endsWith('programs/p1/src/lib.rs'));
  });

  it('skips target/tests/ and falls back to any .rs', () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-findrs-'));
    const target = path.join(workdir, 'target', 'debug');
    mkdirSync(target, { recursive: true });
    writeFileSync(path.join(target, 'whatever.rs'), '');
    const src = path.join(workdir, 'src');
    mkdirSync(src);
    writeFileSync(path.join(src, 'main.rs'), '');
    const found = findPrimaryRustFile(workdir);
    assert.ok(found && found.endsWith('src/main.rs'));
  });
});
