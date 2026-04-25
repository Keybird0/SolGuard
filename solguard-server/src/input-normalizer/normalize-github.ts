// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { spawn as defaultSpawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { config } from '../config';
import { logger } from '../logger';
import type { AuditInput, NormalizedInput } from '../types';

export interface GithubNormalizerDeps {
  spawnFn?: typeof defaultSpawn;
  gitBin?: string;
  timeoutMs?: number;
}

function sanitizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!/^https?:\/\/github\.com\//i.test(trimmed)) {
    throw new Error(`not a github.com URL: ${trimmed}`);
  }
  // Strip `/tree/<branch>/<path>` suffix — we'll just clone the default branch.
  const m = trimmed.match(/^(https?:\/\/github\.com\/[^/]+\/[^/#?]+)(?:[/?#].*)?$/i);
  if (!m || !m[1]) throw new Error(`could not extract repo root from ${trimmed}`);
  return m[1].replace(/\.git$/, '');
}

function slugOf(url: string): string {
  return url
    .replace(/^https?:\/\//, '')
    .replace(/[^a-z0-9]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
}

export async function normalizeGithub(
  input: AuditInput,
  workdir: string,
  deps: GithubNormalizerDeps = {},
): Promise<NormalizedInput> {
  const repoUrl = sanitizeUrl(input.value);
  const targetDir = path.resolve(workdir, 'repos', slugOf(repoUrl));
  mkdirSync(path.dirname(targetDir), { recursive: true });

  if (!existsSync(targetDir)) {
    await clone(repoUrl, targetDir, deps);
  } else {
    logger.debug({ targetDir }, 'github: reusing cached clone');
  }

  const primary = findPrimaryRustFile(targetDir);
  return {
    kind: 'rust_source',
    rootDir: targetDir,
    primaryFile: primary ?? undefined,
    origin: { type: 'github', value: input.value },
  };
}

function clone(
  repoUrl: string,
  targetDir: string,
  deps: GithubNormalizerDeps,
): Promise<void> {
  const spawnFn = deps.spawnFn ?? defaultSpawn;
  const gitBin = deps.gitBin ?? config.gitBin;
  const timeoutMs = deps.timeoutMs ?? config.inputNormalizerTimeoutMs;
  return new Promise<void>((resolve, reject) => {
    const args = ['clone', '--depth=1', '--single-branch', repoUrl, targetDir];
    logger.debug({ gitBin, args, timeoutMs }, 'github: spawning git clone');
    let child;
    try {
      child = spawnFn(gitBin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (err) {
      reject(err instanceof Error ? err : new Error(String(err)));
      return;
    }

    let stderr = '';
    child.stderr?.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf8');
    });
    const timer = setTimeout(() => {
      child.kill('SIGTERM');
      reject(new Error(`git clone timed out after ${timeoutMs} ms`));
    }, timeoutMs);
    timer.unref?.();

    child.on('error', (err: Error) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on('close', (code: number | null) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error(`git clone failed (code=${code}): ${stderr.slice(-400)}`));
    });
  });
}

const SKIP_DIRS = new Set(['target', 'node_modules', '.git', 'vendor', 'tests', 'test']);

export function findPrimaryRustFile(rootDir: string): string | null {
  // Preferred: programs/*/src/lib.rs (Anchor layout)
  const anchorRoot = path.join(rootDir, 'programs');
  if (existsSync(anchorRoot) && statSync(anchorRoot).isDirectory()) {
    for (const name of readdirSync(anchorRoot)) {
      const candidate = path.join(anchorRoot, name, 'src', 'lib.rs');
      if (existsSync(candidate)) return candidate;
    }
  }
  // Fallback: first *.rs found by BFS, skipping SKIP_DIRS.
  const queue: string[] = [rootDir];
  while (queue.length) {
    const current = queue.shift();
    if (!current) break;
    let entries: string[];
    try {
      entries = readdirSync(current);
    } catch {
      continue;
    }
    for (const name of entries) {
      const full = path.join(current, name);
      let st;
      try {
        st = statSync(full);
      } catch {
        continue;
      }
      if (st.isDirectory()) {
        if (!SKIP_DIRS.has(name) && !name.startsWith('.')) queue.push(full);
      } else if (name.endsWith('.rs') && name !== 'build.rs') {
        return full;
      }
    }
  }
  return null;
}
