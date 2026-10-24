"use client";

import { formatElapsed, timeAgo } from "@/lib/api";
import type { ResearchRun, RunSummary } from "@/lib/types";

interface RecentRunsProps {
  runs: RunSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}

function StatusDot({ status }: { status: ResearchRun["status"] }) {
  if (status === "succeeded") return <span className="h-1.5 w-1.5 rounded-full bg-accent" />;
  if (status === "failed") return <span className="h-1.5 w-1.5 rounded-full bg-danger" />;
  if (status === "running") {
    return <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />;
  }
  return <span className="h-1.5 w-1.5 rounded-full bg-mist-500" />;
}

export function RecentRuns({ runs, activeId, loading, onSelect, onRefresh }: RecentRunsProps) {
  return (
    <section className="card card-pad">
      <div className="flex items-center justify-between">
        <div>
          <p className="hud-label">
            <span className="glow-dot" />
            session log
          </p>
          <h2 className="mt-0.5 text-sm font-semibold text-mist-100">Recent runs</h2>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="btn btn-ghost px-2 py-1 text-[0.7rem]"
          aria-label="Refresh recent runs"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="none"
            aria-hidden="true"
            className={loading ? "animate-spin" : ""}
          >
            <path
              d="M13 8a5 5 0 1 1-1.6-3.7M13 2.5V5h-2.5"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Refresh
        </button>
      </div>

      {runs.length === 0 ? (
        <p className="mt-4 text-xs leading-relaxed text-mist-500">
          No runs in this server session yet. Start one above — it will show up here while it runs
          and after it finishes.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-ink-700/70">
          {runs.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => onSelect(run.id)}
                aria-current={activeId === run.id ? "true" : undefined}
                title={run.topic}
                className={`flex w-full items-start gap-2.5 rounded-lg px-1.5 py-2.5 text-left transition hover:bg-ink-800/70 ${
                  activeId === run.id ? "bg-ink-800/70 ring-1 ring-accent/30" : ""
                }`}
              >
                <span className="mt-1.5">
                  <StatusDot status={run.status} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-mist-300">
                    {run.topic}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1.5 font-mono text-[0.64rem] text-mist-500">
                    <span>{timeAgo(run.created_at)}</span>
                    <span>·</span>
                    <span>{run.source_count} sources</span>
                    {run.status === "succeeded" && run.elapsed_seconds > 0 ? (
                      <>
                        <span>·</span>
                        <span>{formatElapsed(run.elapsed_seconds)}</span>
                      </>
                    ) : null}
                    {run.status === "running" || run.status === "queued" ? (
                      <>
                        <span>·</span>
                        <span className="text-accent-soft">
                          {run.status === "running" ? "running" : "queued"}
                        </span>
                      </>
                    ) : null}
                    {run.status === "failed" ? (
                      <>
                        <span>·</span>
                        <span className="text-danger">failed</span>
                      </>
                    ) : null}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}



