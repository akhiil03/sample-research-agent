export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface Source {
  title: string;
  url: string;
  snippet: string;
  kind: "search" | "page";
}

export interface RunEvent {
  stage: string;
  status?: string;
  at?: string;
  round?: number;
  rounds?: number;
  sources?: number;
  tool_calls?: number;
  results?: number;
  sufficient?: boolean;
  output_path?: string;
  queries?: string[];
  gaps?: string[];
  [key: string]: unknown;
}

export interface ResearchRun {
  id: string;
  topic: string;
  model: string;
  max_iterations: number;
  status: RunStatus;
  stage: string;
  message: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  rounds: number;
  source_count: number;
  sources: Source[];
  events: RunEvent[];
  report: string;
  output_path: string;
  error: string | null;
  elapsed_seconds: number;
  usage: Record<string, number>;
}

export interface Health {
  status: string;
  provider?: string;
  default_model: string;
  fake_model: boolean;
  has_api_key: boolean;
}

export interface StartRunPayload {
  topic: string;
  model?: string;
  max_iterations: number;
}

export type RunSummary = Pick<
  ResearchRun,
  | "id"
  | "topic"
  | "model"
  | "max_iterations"
  | "status"
  | "stage"
  | "message"
  | "created_at"
  | "started_at"
  | "finished_at"
  | "rounds"
  | "source_count"
  | "elapsed_seconds"
>;