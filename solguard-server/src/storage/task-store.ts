import type { AuditTask } from '../types';

export interface TaskStore {
  create(task: AuditTask): Promise<AuditTask>;
  get(id: string): Promise<AuditTask | null>;
  update(id: string, patch: Partial<AuditTask>): Promise<AuditTask>;
  list(filter?: { status?: AuditTask['status']; limit?: number }): Promise<AuditTask[]>;
  delete(id: string): Promise<void>;
}

export class InMemoryTaskStore implements TaskStore {
  private readonly tasks = new Map<string, AuditTask>();

  async create(task: AuditTask): Promise<AuditTask> {
    if (this.tasks.has(task.taskId)) {
      throw new Error(`Task ${task.taskId} already exists`);
    }
    this.tasks.set(task.taskId, { ...task });
    return { ...task };
  }

  async get(id: string): Promise<AuditTask | null> {
    const task = this.tasks.get(id);
    return task ? { ...task } : null;
  }

  async update(id: string, patch: Partial<AuditTask>): Promise<AuditTask> {
    const existing = this.tasks.get(id);
    if (!existing) {
      throw new Error(`Task ${id} not found`);
    }
    const updated: AuditTask = {
      ...existing,
      ...patch,
      taskId: existing.taskId,
      updatedAt: new Date().toISOString(),
    };
    this.tasks.set(id, updated);
    return { ...updated };
  }

  async list(filter: { status?: AuditTask['status']; limit?: number } = {}): Promise<AuditTask[]> {
    let results = Array.from(this.tasks.values()).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
    if (filter.status) {
      results = results.filter((t) => t.status === filter.status);
    }
    if (filter.limit && filter.limit > 0) {
      results = results.slice(0, filter.limit);
    }
    return results.map((t) => ({ ...t }));
  }

  async delete(id: string): Promise<void> {
    this.tasks.delete(id);
  }
}

let singleton: TaskStore | null = null;

export function getTaskStore(): TaskStore {
  if (!singleton) {
    singleton = new InMemoryTaskStore();
  }
  return singleton;
}
