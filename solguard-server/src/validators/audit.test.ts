// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { strict as assert } from 'node:assert';
import { describe, it } from 'node:test';
import {
  agentCompleteSchema,
  createAuditSchema,
  createBatchSchema,
  feedbackSchema,
  targetSchema,
  targetToInputs,
} from './audit';

describe('createAuditSchema', () => {
  it('accepts a valid github input', () => {
    const parsed = createAuditSchema.parse({
      inputs: [{ type: 'github', value: 'https://github.com/solana-labs/example' }],
      email: 'x@y.com',
    });
    assert.equal(parsed.inputs.length, 1);
  });

  it('rejects too many inputs', () => {
    const inputs = Array.from({ length: 6 }, () => ({
      type: 'website' as const,
      value: 'https://a.com',
    }));
    assert.throws(() =>
      createAuditSchema.parse({ inputs, email: 'x@y.com' }),
    );
  });

  it('rejects bad solana address', () => {
    assert.throws(() =>
      createAuditSchema.parse({
        inputs: [{ type: 'contract_address', value: 'not-base58' }],
        email: 'x@y.com',
      }),
    );
  });
});

describe('agentCompleteSchema', () => {
  it('accepts minimal success payload', () => {
    const parsed = agentCompleteSchema.parse({ status: 'completed' });
    assert.equal(parsed.status, 'completed');
  });

  it('accepts failure with error string', () => {
    const parsed = agentCompleteSchema.parse({ status: 'failed', error: 'boom' });
    assert.equal(parsed.error, 'boom');
  });
});

describe('targetSchema', () => {
  it('accepts a target with github + moreInfo', () => {
    const parsed = targetSchema.parse({
      github: 'https://github.com/solana-labs/example',
      moreInfo: 'upgraded last week',
    });
    assert.equal(parsed.github, 'https://github.com/solana-labs/example');
    assert.equal(parsed.moreInfo, 'upgraded last week');
  });

  it('rejects a target with no primary field (moreInfo only)', () => {
    assert.throws(() =>
      targetSchema.parse({ moreInfo: 'just some text' }),
    );
  });

  it('rejects a totally empty target', () => {
    assert.throws(() => targetSchema.parse({}));
  });

  it('rejects moreInfo > 2000 chars', () => {
    assert.throws(() =>
      targetSchema.parse({
        github: 'https://github.com/solana-labs/example',
        moreInfo: 'x'.repeat(2001),
      }),
    );
  });

  it('accepts moreInfo = 2000 chars exactly', () => {
    const parsed = targetSchema.parse({
      github: 'https://github.com/solana-labs/example',
      moreInfo: 'x'.repeat(2000),
    });
    assert.equal(parsed.moreInfo?.length, 2000);
  });

  it('rejects bad github url', () => {
    assert.throws(() =>
      targetSchema.parse({ github: 'https://not-github.com/a/b' }),
    );
  });

  it('rejects bad solana address', () => {
    assert.throws(() =>
      targetSchema.parse({ contractAddress: 'not-base58' }),
    );
  });
});

describe('createBatchSchema', () => {
  it('accepts 1-5 targets', () => {
    const parsed = createBatchSchema.parse({
      targets: [
        { github: 'https://github.com/a/b' },
        { website: 'https://example.com' },
      ],
      email: 'x@y.com',
    });
    assert.equal(parsed.targets.length, 2);
  });

  it('rejects 0 targets', () => {
    assert.throws(() =>
      createBatchSchema.parse({ targets: [], email: 'x@y.com' }),
    );
  });

  it('rejects >5 targets', () => {
    const targets = Array.from({ length: 6 }, (_, i) => ({
      github: `https://github.com/a/b${i}`,
    }));
    assert.throws(() =>
      createBatchSchema.parse({ targets, email: 'x@y.com' }),
    );
  });
});

describe('targetToInputs', () => {
  it('maps non-empty fields to AuditInput[]', () => {
    const inputs = targetToInputs({
      github: 'https://github.com/a/b',
      website: 'https://example.com',
      moreInfo: 'extra context',
    });
    assert.equal(inputs.length, 3);
    assert.deepEqual(
      inputs.map((i) => i.type).sort(),
      ['github', 'more_info', 'website'],
    );
  });

  it('skips undefined fields', () => {
    const inputs = targetToInputs({ github: 'https://github.com/a/b' });
    assert.equal(inputs.length, 1);
    assert.equal(inputs[0]?.type, 'github');
  });
});

describe('feedbackSchema', () => {
  it('requires rating between 1 and 5', () => {
    assert.throws(() => feedbackSchema.parse({ rating: 0 }));
    assert.throws(() => feedbackSchema.parse({ rating: 6 }));
    assert.equal(feedbackSchema.parse({ rating: 3 }).rating, 3);
  });
});
