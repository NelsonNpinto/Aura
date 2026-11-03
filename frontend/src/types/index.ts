export interface Overview {
  total_requests: number;
  evaluation_runs: number;
  average_check_score: number | null;
  request_errors: number;
  failed_evaluations: number;
  average_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  faithfulness: number | null;
  answer_relevance: number | null;
  estimated_cost: number | null;
  unsupported_claim_reviews: number;
  judge_reviews: number;
  dataset_runs: number;
  model_comparison: { model: string; requests: number; latency_ms: number }[];
}
export interface Trace {
  id: string;
  created_at: string;
  model: string;
  prompt: string;
  system: string;
  response: string | null;
  status: string;
  error: string | null;
  latency_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  configuration: { temperature: number; max_tokens: number; model: string };
}
export interface Evaluation {
  id: string;
  created_at: string;
  name: string;
  response: string;
  score: number;
  passed: boolean;
  trace_id: string | null;
  results: { kind: string; passed: boolean; detail: string; method: string }[];
}
export interface ModelStatus {
  available: boolean;
  models: { name: string; size: number }[];
  message?: string;
}
export type CheckKind =
  | "non_empty"
  | "valid_json"
  | "json_schema"
  | "required_keywords"
  | "forbidden_phrases"
  | "exact_match";
