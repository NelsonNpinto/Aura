import type { CheckKind } from "./index";
export interface Rule {
  kind: CheckKind;
  values?: string[];
  expected?: string;
  schema_definition?: Record<string, unknown>;
}
export interface SavedPrompt {
  id: string;
  name: string;
  version: number;
  system: string;
  template: string;
  configuration: Record<string, unknown>;
  created_at: string;
}
export interface Dataset {
  id: string;
  name: string;
  description: string;
  created_at: string;
}
export interface TestCase {
  id: string;
  question: string;
  expected: string | null;
  response: string | null;
  contexts: string[];
  checks: Rule[];
}
export interface BatchRun {
  id: string;
  dataset_id: string;
  configuration: RunConfig;
  score: number;
  passed: boolean;
  latency_ms: number;
  errors: number;
  gate: {
    passed?: boolean;
    reason?: string;
    checks?: Record<string, boolean>;
    score_delta?: number;
  };
  created_at: string;
  results?: unknown[];
}
export interface RunConfig {
  mode: "stored" | "generate" | "rag";
  model: string;
  system?: string;
  template?: string;
  temperature?: number;
  max_tokens?: number;
  seed?: number;
  threshold?: number;
  retrieval?: "bm25" | "vector" | "hybrid";
  top_k?: number;
  prompt_id?: string;
  judge_model?: string;
}
export interface KnowledgeDocument {
  id: string;
  name: string;
  chunk_count: number;
  embedding_model: string | null;
  created_at: string;
}
export interface Source {
  id: string;
  document_id: string;
  document: string;
  position: number;
  content: string;
  rank_score: number;
  citation?: number;
  cited?: boolean;
}
export interface JudgeReview {
  id: string;
  question: string;
  response: string;
  expected: string | null;
  contexts: string[];
  score: number | null;
  passed: boolean | null;
  error: string | null;
  verdict: Record<
    string,
    | { score: number; explanation: string }
    | string[]
    | Record<string, number | null>
    | string
  >;
  engine: string;
  configuration: { model: string; rubric: string; threshold: number };
  created_at: string;
}
export interface Reliability {
  sample_size: number;
  agreement: number | null;
  kappa: number | null;
  mean_absolute_score_error?: number;
  false_passes: string[];
  false_fails: string[];
  message: string;
}
export interface AgentRun {
  id: string;
  task: string;
  response: string;
  steps: {
    tool?: string;
    arguments?: Record<string, unknown>;
    result?: string;
    error?: string;
    trace_id: string;
  }[];
  metrics: Record<string, unknown>;
  passed: boolean;
  created_at: string;
}
export interface FailureEvent {
  id: string;
  event_id: string;
  source: string;
  question: string;
  response: string;
  error: string;
  status: string;
  case_id: string | null;
  created_at: string;
}
export interface CheckResult {
  kind: string;
  passed: boolean;
  detail: string;
  method: string;
}
export interface MarketingReview {
  id: string;
  content: string;
  results: CheckResult[];
  score: number;
  decision: string;
  reviewer: string | null;
  feedback: string | null;
  created_at: string;
}
export interface SecurityRun {
  id: string;
  model: string;
  score: number;
  created_at: string;
  results: {
    id: string;
    category: string;
    attack: string;
    response: string | null;
    error: string | null;
    passed: boolean;
    trace_id: string;
  }[];
}
export interface Experiment {
  id: string;
  name: string;
  dataset_id: string;
  created_at: string;
  results: {
    run_id: string;
    score: number;
    latency_ms: number;
    errors: number;
    passed: boolean;
    configuration: RunConfig;
    metrics?: {
      input_tokens: number | null;
      output_tokens: number | null;
      faithfulness: number | null;
      answer_relevance: number | null;
      judge_quality_score: number | null;
      estimated_provider_cost_usd: number | null;
    };
  }[];
}
export interface Monitoring {
  counts: Record<string, number>;
  window_requests: number;
  window_limit: number;
  error_rate: number | null;
  p95_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cloud_inference_cost_usd: number | null;
  cost_note: string;
  otel_configured: boolean;
  langfuse_configured: boolean;
  api_auth_enabled: boolean;
  webhook_enabled: boolean;
  operations: Record<string, number>;
  recent_errors: {
    id: string;
    model: string;
    error: string;
    created_at: string;
  }[];
}
