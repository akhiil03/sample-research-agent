import type { Health, ResearchRun, RunSummary, StartRunPayload } from "./types";

const BASE_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      cache: "no-store",
      headers: { "content-type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${BASE_URL}. Is the FastAPI server running?`, 0);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : Array.isArray(body?.detail)
          ? body.detail
              .map((item) => (typeof item === "object" && item && "msg" in item ? item.msg : ""))
              .join(", ")
          : `Request failed with status ${response.status}`;
    throw new ApiError(String(detail), response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  baseUrl: BASE_URL,
  health: () => request<Health>("/api/health"),
  startRun: (payload: StartRunPayload) =>
    request<ResearchRun>("/api/runs", { method: "POST", body: JSON.stringify(payload) }),
  getRun: (id: string) => request<ResearchRun>(`/api/runs/${id}`),
  listRuns: (limit = 12) => request<{ runs: RunSummary[] }>(`/api/runs?limit=${limit}`),
};

export function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}m ${rest.toString().padStart(2, "0")}s`;
}

export function stripFrontmatter(markdown: string): string {
  return markdown.replace(/^---\n[\s\S]*?\n---\n+/, "").trim();
}

export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

