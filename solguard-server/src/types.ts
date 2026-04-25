export type TaskStatus =
  | 'pending'
  | 'paying'
  | 'paid'
  | 'scanning'
  | 'analyzing'
  | 'reporting'
  | 'completed'
  | 'failed';

export type InputType =
  | 'github'
  | 'contract_address'
  | 'whitepaper'
  | 'website'
  | 'more_info';

export interface AuditInput {
  type: InputType;
  value: string;
}

/**
 * Target = one project being audited. A submission can carry multiple
 * Targets (each becomes its own AuditTask); all tasks share a single
 * AuditBatch for atomic pricing and payment.
 */
export interface AuditTarget {
  github?: string;
  contractAddress?: string;
  whitepaper?: string;
  website?: string;
  moreInfo?: string;
}

export type BatchStatus = 'paying' | 'paid' | 'failed';

export interface AuditBatch {
  batchId: string;
  taskIds: string[];
  email: string;

  status: BatchStatus;
  totalAmountSol: number;

  paymentReference?: string;
  paymentRecipient?: string;
  paymentUrl?: string;
  paymentSignature?: string;
  paymentExpiresAt?: string;
  paymentConfirmedAt?: string;

  cluster: string;
  freeAudit?: boolean;

  createdAt: string;
  updatedAt: string;
}

export type NormalizedInput =
  | {
      kind: 'rust_source';
      rootDir: string;
      primaryFile?: string;
      /**
       * Optional list of Rust files discovered under `rootDir` (relative or
       * absolute paths). The AI-first planner in `run_audit.py` consumes
       * this to build an inventory without re-walking the filesystem. When
       * omitted, the planner falls back to walking `rootDir` itself. Empty
       * array is not the same as omitted — callers should pass `undefined`
       * to signal "no inventory attempt was made".
       */
      files?: string[];
      origin: AuditInput;
    }
  | {
      kind: 'bytecode_only';
      programId: string;
      bytecodePath: string;
      origin: AuditInput;
    }
  | {
      kind: 'lead_only';
      leadsJsonPath: string;
      origin: AuditInput;
    };

export type Severity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';

export interface Finding {
  id: string;
  ruleId?: string;
  severity: Severity;
  title: string;
  location: string;
  description: string;
  impact: string;
  recommendation: string;
  codeSnippet?: string;
  confidence?: number;
  killSignal?: {
    isValid: boolean;
    reason: string;
  };
}

export interface Statistics {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
  total: number;
}

export interface AuditTask {
  taskId: string;
  batchId?: string;
  inputs: AuditInput[];
  email: string;

  status: TaskStatus;
  progress?: string;
  progressPercent?: number;

  paymentReference?: string;
  paymentSignature?: string;
  paymentAmountSol?: number;
  paymentRecipient?: string;
  paymentUrl?: string;
  paymentExpiresAt?: string;

  normalizedInputs?: NormalizedInput[];
  normalizeError?: string;

  findings?: Finding[];
  statistics?: Statistics;
  reportMarkdown?: string;
  reportUrl?: string;

  error?: string;

  createdAt: string;
  updatedAt: string;
  completedAt?: string;
}

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface AgentEvent {
  type:
    | 'tool_call_start'
    | 'tool_call_end'
    | 'thought'
    | 'final_result'
    | 'error'
    | 'unknown';
  tool?: string;
  data?: unknown;
  raw?: string;
}
