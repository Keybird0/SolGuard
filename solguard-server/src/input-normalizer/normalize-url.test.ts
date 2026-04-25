// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { mkdtempSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { describe, it } from 'node:test';
import { normalizeUrl, extractLeads } from './normalize-url';

function mockFetch(body: string, status = 200): typeof fetch {
  return (async () =>
    ({
      status,
      ok: status >= 200 && status < 300,
      text: async () => body,
      headers: new Headers(),
    }) as unknown as Response) as typeof fetch;
}

describe('extractLeads', () => {
  it('extracts github URLs and dedupes', () => {
    const text =
      'source: https://github.com/foo/bar and https://github.com/foo/bar#readme ' +
      'also https://github.com/baz/qux';
    const leads = extractLeads(text);
    assert.equal(leads.length, 2);
    assert.equal(leads[0].type, 'github');
    assert.equal(leads[0].value, 'https://github.com/foo/bar');
    assert.equal(leads[1].value, 'https://github.com/baz/qux');
  });

  it('extracts base58 Solana addresses', () => {
    const text = 'Program ID: TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA (canonical)';
    const leads = extractLeads(text);
    const addr = leads.find((l) => l.type === 'contract_address');
    assert.ok(addr);
    assert.equal(addr!.value, 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA');
  });
});

describe('normalizeUrl', () => {
  it('returns lead_only + followUp when html contains github url', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-url-'));
    const html =
      '<html><body>See our <a href="https://github.com/foo/bar">code</a></body></html>';
    const res = await normalizeUrl(
      { type: 'website', value: 'https://example.com/project' },
      workdir,
      { fetchImpl: mockFetch(html) },
    );
    assert.equal(res.kind, 'lead_only');
    assert.equal(res.followUp?.type, 'github');
    assert.equal(res.followUp?.value, 'https://github.com/foo/bar');
  });

  it('returns lead_only without followUp when no leads found', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-url-'));
    const html = '<html><body>Just marketing copy, nothing to see.</body></html>';
    const res = await normalizeUrl(
      { type: 'website', value: 'https://example.com/hype' },
      workdir,
      { fetchImpl: mockFetch(html) },
    );
    assert.equal(res.kind, 'lead_only');
    assert.equal(res.followUp, undefined);
  });

  it('routes through llmExtractor when provided', async () => {
    const workdir = mkdtempSync(path.join(tmpdir(), 'solguard-url-'));
    const res = await normalizeUrl(
      { type: 'whitepaper', value: 'https://example.com/wp.pdf' },
      workdir,
      {
        fetchImpl: mockFetch('plain text with no github links'),
        llmExtractor: async () => [
          { type: 'contract_address', value: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' },
        ],
      },
    );
    assert.equal(res.followUp?.type, 'contract_address');
  });
});
