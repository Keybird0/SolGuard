// SPDX-License-Identifier: MIT
// Copyright (c) 2026 SolGuard Contributors
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import type { AuditTask } from '../types';
import type { TaskStore } from './task-store';

export class FileJsonTaskStore implements TaskStore {
  private readonly dir: string;
  private readonly cache = new Map<string, AuditTask>();

  constructor(dir: string) {
    this.dir = path.resolve(dir);
    mkdirSync(this.dir, { recursive: true });
    this.loadAll();
  }

  private loadAll(): void {
    let entries: string[] = [];
    try {
      entries = readdirSync(this.dir);
    } catch {
      return;
    }
    for (const entry of entries) {
      if (!entry.endsWith('.json')) continue;
      try {
        const raw = readFileSync(path.join(this.dir, entry), 'utf8');
        const task = JSON.parse(raw) as AuditTask;
        this.cache.set(task.taskId, task);
      } catch {
        // skip corrupted files
      }
    }
  }

  private persist(task: AuditTask): void {
    const file = path.join(this.dir, `${task.taskId}.json`);
    writeFileSync(file, JSON.stringify(task, null, 2), 'utf8');
  }

  async create(task: AuditTask): Promise<AuditTask> {
    if (this.cache.has(task.taskId)) {
      throw new Error(`Task ${task.taskId} already exists`);
    }
    const copy = { ...task };
    this.cache.set(task.taskId, copy);
    this.persist(copy);
    return { ...copy };
  }

  async get(id: string): Promise<AuditTask | null> {
    const task = this.cache.get(id);
    return task ? { ...task } : null;
  }

  async update(id: string, patch: Partial<AuditTask>): Promise<AuditTask> {
    const existing = this.cache.get(id);
    if (!existing) throw new Error(`Task ${id} not found`);
    const updated: AuditTask = {
      ...existing,
      ...patch,
      taskId: existing.taskId,
      updatedAt: new Date().toISOString(),
    };
    this.cache.set(id, updated);
    this.persist(updated);
    return { ...updated };
  }

  async list(
    filter: { status?: AuditTask['status']; limit?: number } = {},
  ): Promise<AuditTask[]> {
    let results = Array.from(this.cache.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
    if (filter.status) results = results.filter((t) => t.status === filter.status);
    if (filter.limit && filter.limit > 0) results = results.slice(0, filter.limit);
    return results.map((t) => ({ ...t }));
  }

  async delete(id: string): Promise<void> {
    this.cache.delete(id);
  }
}
