// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
//
// In-memory AuditBatch store (mirrors InMemoryTaskStore). A batch groups
// N sibling AuditTasks created by a single submission so they share one
// Solana Pay reference/signature and are priced atomically (N × fee).
//
// Persistence is explicitly out of scope for Phase 4.6 — the frontend
// polls `/api/audit/batch/:id` on a 2s interval and receives the
// authoritative state; a server restart invalidates unpaid batches,
// which is acceptable while we target Devnet / demo usage.
import type { AuditBatch, BatchStatus } from '../types';

export interface BatchStore {
  create(batch: AuditBatch): Promise<AuditBatch>;
  get(id: string): Promise<AuditBatch | null>;
  update(id: string, patch: Partial<AuditBatch>): Promise<AuditBatch>;
  list(filter?: { status?: BatchStatus; limit?: number }): Promise<AuditBatch[]>;
  delete(id: string): Promise<void>;
}

export class InMemoryBatchStore implements BatchStore {
  private readonly batches = new Map<string, AuditBatch>();

  async create(batch: AuditBatch): Promise<AuditBatch> {
    if (this.batches.has(batch.batchId)) {
      throw new Error(`Batch ${batch.batchId} already exists`);
    }
    this.batches.set(batch.batchId, { ...batch });
    return { ...batch };
  }

  async get(id: string): Promise<AuditBatch | null> {
    const batch = this.batches.get(id);
    return batch ? { ...batch } : null;
  }

  async update(id: string, patch: Partial<AuditBatch>): Promise<AuditBatch> {
    const existing = this.batches.get(id);
    if (!existing) {
      throw new Error(`Batch ${id} not found`);
    }
    const updated: AuditBatch = {
      ...existing,
      ...patch,
      batchId: existing.batchId,
      updatedAt: new Date().toISOString(),
    };
    this.batches.set(id, updated);
    return { ...updated };
  }

  async list(
    filter: { status?: BatchStatus; limit?: number } = {},
  ): Promise<AuditBatch[]> {
    let results = Array.from(this.batches.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
    if (filter.status) {
      results = results.filter((b) => b.status === filter.status);
    }
    if (filter.limit && filter.limit > 0) {
      results = results.slice(0, filter.limit);
    }
    return results.map((b) => ({ ...b }));
  }

  async delete(id: string): Promise<void> {
    this.batches.delete(id);
  }
}

let singleton: BatchStore | null = null;

export function getBatchStore(): BatchStore {
  if (!singleton) {
    singleton = new InMemoryBatchStore();
  }
  return singleton;
}

export function setBatchStoreForTesting(store: BatchStore | null): void {
  singleton = store;
}
