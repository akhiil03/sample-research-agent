import { ApiError } from "./errors";
import type { Health, ResearchRun, RunStatus, RunSummary, StartRunPayload } from "./types";

const REPO = (process.env.NEXT_PUBLIC_GITHUB_REPO ?? "").trim();
const DEFAULT_MODEL = (process.env.NEXT_PUBLIC_DEFAULT_MODEL ?? "gemini-3.5-flash-lite").trim();
const BRANCH = "status";
const API = "https://api.github.com";
const RAW = "https://raw.githubusercontent.com";
const TOKEN_KEY = "research-agent.github-token";
const STUB_PREFIX = "research-agent.run-stub.";

export const GITHUB_MODE = REPO.length > 0;

export function ghActionsUrl(): string {
  return `https://github.com/${REPO}/actions`;
}

export function readToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    if (token.trim()) window.localStorage.setItem(TOKEN_KEY, token.trim());
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage can be unavailable in private browsing; runs then fail with a clear message.
  }
}

interface Stub {
  topic: string;
  model: string;
  max_iterations: number;
  created_at: string;
}

function saveStub(id: string, stub: Stub): void {
  try {
    window.localStorage.setItem(`${STUB_PREFIX}${id}`, JSON.stringify(stub));
  } catch {
    // ignore
  }
}

function readStub(id: string): Stub | null {
  try {
    const raw = window.localStorage.getItem(`${STUB_PREFIX}${id}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Stub>;
    if (!parsed.topic) return null;
    return {
      topic: parsed.topic,
      model: parsed.model ?? DEFAULT_MODEL,
      max_iterations: parsed.max_iterations ?? 2,
      created_at: parsed.created_at ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

async function ghRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const token = readToken();
  const headers: Record<string, string> = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init?.body) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { cache: "no-store", ...init, headers });
  } catch {
    throw new ApiError("Cannot reach api.github.com from this browser.", 0);
  }
  if (response.status === 401 || response.status === 403) {
    throw new ApiError(
      "GitHub rejected the token. Add a fine-grained token with Actions: write and Contents: read access.",
      response.status,
    );
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new ApiError(body?.message ?? `GitHub request failed (${response.status}).`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function rawUrl(id: string): string {
  return `${RAW}/${REPO}/${BRANCH}/runs/${id}.json`;
}

function queuedRun(id: string, stub: Stub): ResearchRun {
  const waits = (Date.now() - new Date(stub.created_at).getTime()) / 1000;
  return {
    id,
    topic: stub.topic,
    model: stub.model,
    max_iterations: stub.max_iterations,
    status: "queued",
    stage: "queued",
    message:
      waits > 90
        ? "Still queued on GitHub. Open the Actions tab to check the run."
        : "Workflow queued on GitHub Actions...",
    created_at: stub.created_at,
    started_at: null,
    finished_at: null,
    rounds: 0,
    source_count: 0,
    sources: [],
    events: [],
    report: "",
    output_path: "",
    error: null,
    elapsed_seconds: Math.max(0, Math.round(waits)),
    usage: {},
  };
}

function normalize(id: string, data: Partial<ResearchRun>): ResearchRun {
  const status: RunStatus =
    data.status === "succeeded" || data.status === "failed" || data.status === "running"
      ? data.status
      : "running";
  return {
    id,
    topic: data.topic ?? "Untitled run",
    model: data.model ?? DEFAULT_MODEL,
    max_iterations: data.max_iterations ?? 2,
    status,
    stage: data.stage ?? "running",
    message: data.message ?? "Working",
    created_at: data.created_at ?? new Date().toISOString(),
    started_at: data.started_at ?? null,
    finished_at: data.finished_at ?? null,
    rounds: data.rounds ?? 0,
    source_count: data.source_count ?? 0,
    sources: data.sources ?? [],
    events: Array.isArray(data.events) ? data.events : [],
    report: data.report ?? "",
    output_path: data.output_path ?? "",
    error: data.error ?? null,
    elapsed_seconds: data.elapsed_seconds ?? 0,
    usage: data.usage ?? {},
  };
}

interface ContentsItem {
  name?: string;
  type?: string;
}

export const githubApi = {
  baseUrl: `github.com/${REPO}`,

  async health(): Promise<Health> {
    return {
      status: "ok",
      provider: "github-actions",
      default_model: DEFAULT_MODEL,
      fake_model: false,
      has_api_key: true,
    };
  },

  async startRun(payload: StartRunPayload): Promise<ResearchRun> {
    if (!readToken()) {
      throw new ApiError(
        "Add a GitHub token in the GitHub Actions panel so this page can start a run.",
        401,
      );
    }
    const id = `run_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
    const model = payload.model?.trim() || "";
    await ghRequest(`/repos/${REPO}/actions/workflows/agent.yml/dispatches`, {
      method: "POST",
      body: JSON.stringify({
        ref: "main",
        inputs: {
          topic: payload.topic,
          model,
          max_iterations: String(payload.max_iterations),
          run_id: id,
        },
      }),
    });
    const stub: Stub = {
      topic: payload.topic,
      model: model || DEFAULT_MODEL,
      max_iterations: payload.max_iterations,
      created_at: new Date().toISOString(),
    };
    saveStub(id, stub);
    return queuedRun(id, stub);
  },

  async getRun(id: string): Promise<ResearchRun> {
    const response = await fetch(`${rawUrl(id)}?v=${Date.now()}`, { cache: "no-store" });
    if (response.status === 404) {
      const stub = readStub(id);
      if (!stub) throw new ApiError("Run not found. It may have expired.", 404);
      return queuedRun(id, stub);
    }
    if (!response.ok) {
      throw new ApiError(`Cannot read run status (${response.status}).`, response.status);
    }
    const data = (await response.json()) as Partial<ResearchRun>;
    const stub = readStub(id);
    if (stub) {
      data.topic = data.topic ?? stub.topic;
      data.model = data.model ?? stub.model;
      data.max_iterations = data.max_iterations ?? stub.max_iterations;
      data.created_at = data.created_at ?? stub.created_at;
    }
    return normalize(id, data);
  },

  async listRuns(limit = 12): Promise<{ runs: RunSummary[] }> {
    let items: ContentsItem[];
    try {
      items = await ghRequest<ContentsItem[]>(`/repos/${REPO}/contents/runs?ref=${BRANCH}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return { runs: [] };
      throw error;
    }
    const names = items
      .filter((item) => item.type === "file" && item.name?.endsWith(".json"))
      .map((item) => item.name as string)
      .sort()
      .reverse()
      .slice(0, Math.max(limit, 12));

    const loaded = await Promise.all(
      names.map(async (name) => {
        const id = name.replace(/\.json$/, "");
        try {
          const response = await fetch(`${rawUrl(id)}?v=${Date.now()}`, { cache: "no-store" });
          if (!response.ok) return null;
          return normalize(id, (await response.json()) as Partial<ResearchRun>);
        } catch {
          return null;
        }
      }),
    );

    const runs: RunSummary[] = loaded
      .filter((run): run is ResearchRun => run !== null)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      .slice(0, limit)
      .map((run) => ({
        id: run.id,
        topic: run.topic,
        model: run.model,
        max_iterations: run.max_iterations,
        status: run.status,
        stage: run.stage,
        message: run.message,
        created_at: run.created_at,
        started_at: run.started_at,
        finished_at: run.finished_at,
        rounds: run.rounds,
        source_count: run.source_count,
        elapsed_seconds: run.elapsed_seconds,
      }));
    return { runs };
  },
};
