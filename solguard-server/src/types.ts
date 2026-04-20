export type TaskStatus =
  | 'pending'
  | 'paying'
  | 'paid'
  | 'scanning'
  | 'analyzing'
  | 'reporting'
  | 'completed'
  | 'failed';

export type InputType = 'github' | 'contract_address' | 'whitepaper' | 'website';

export interface AuditInput {
  type: InputType;
  value: string;
}

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
  inputs: AuditInput[];
  email: string;

  status: TaskStatus;
  progress?: string;
  progressPercent?: number;

  paymentReference?: string;
  paymentSignature?: string;
  paymentAmountSol?: number;

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
