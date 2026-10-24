"use client";

import { useEffect, useState } from "react";

import { AgentFace } from "@/components/AgentFace";
import { formatElapsed } from "@/lib/api";
import { describeEvent } from "@/lib/event";
import type { ResearchRun } from "@/lib/types";

const MAX_LOG = 8;

function timestamp(at?: string): string {
  if (!at) return "--:--:--";
  return new Date(at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function useElapsed(run: ResearchRun): number {
  const running = run.status === "queued" || run.status === "running";
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);

  if (!running) return run.elapsed_seconds;
  if (!run.started_at) return 0;
  return Math.max(0, (now - new Date(run.started_at).getTime()) / 1000);
}

function StatusPill({ run }: { run: ResearchRun }) {
  const base = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.7rem] font-semibold";
  if (run.status === "succeeded") {
    return <span className={`${base} bg-accent/10 text-accent-soft`}>Completed</span>;
  }
  if (run.status === "failed") {
    return <span className={`${base} bg-danger/10 text-danger`}>Failed</span>;
  }
  return (
    <span className={`${base} bg-ink-700 text-mist-300`}>
      <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
      {run.status === "queued" ? "Queued" : "Working"}
    </span>
  );
}

function EventChips({ queries, gaps }: { queries: string[]; gaps: string[] }) {
  if (queries.length === 0 && gaps.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {queries.slice(0, 8).map((query, index) => (
        <span
          key={`q-${index}-${query}`}
          className="chip max-w-full border-accent/25 font-mono text-[0.62rem] text-accent-soft/90"
          title={query}
        >
          <svg width="9" height="9" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="shrink-0">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.6" />
            <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <span className="max-w-[15rem] truncate">{query}</span>
        </span>
      ))}
      {gaps.slice(0, 6).map((gap, index) => (
        <span
          key={`g-${index}-${gap}`}
          className="chip max-w-full border-warn/35 font-mono text-[0.62rem] text-warn"
          title={gap}
        >
          <span className="max-w-[13rem] truncate">{gap}</span>
        </span>
      ))}
    </div>
  );
}

export function RunProgress({ run, stale = false }: { run: ResearchRun; stale?: boolean }) {
  const elapsed = useElapsed(run);
  const failed = run.status === "failed";
  const succeeded = run.status === "succeeded";
  const running = run.status === "queued" || run.status === "running";
  const log = run.events
    .filter((event) => event.stage !== "failed")
    .slice(-MAX_LOG)
    .reverse();
  const planEvent = [...run.events].reverse().find((event) => event.stage === "plan");
  const critiqueEvent = [...run.events].reverse().find((event) => event.stage === "critique");
  const queries = Array.isArray(planEvent?.queries) ? planEvent.queries.filter(Boolean) : [];
  const gaps = Array.isArray(critiqueEvent?.gaps) ? critiqueEvent.gaps.filter(Boolean) : [];

  return (
    <section className="card card-pad hud" aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[0.65rem] uppercase tracking-[0.16em] text-mist-500">
            Agent run
          </p>
          <h2 className="mt-1 truncate text-lg font-semibold tracking-tight text-mist-100">
            {run.topic}
          </h2>
          <p className="mt-1 font-mono text-xs text-mist-500">{run.model}</p>
        </div>
        <StatusPill run={run} />
        {stale && !failed && !succeeded ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/40 bg-ink-850 px-2.5 py-1 text-[0.7rem] font-semibold text-warn">
            <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-warn" />
            Reconnecting
          </span>
        ) : null}
      </div>

      <div className="mt-5 grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2">
          <p className="text-[0.62rem] uppercase tracking-wider text-mist-500">Round</p>
          <p className="mt-0.5 font-mono text-sm text-mist-100">
            {run.rounds}/{run.max_iterations}
          </p>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2">
          <p className="text-[0.62rem] uppercase tracking-wider text-mist-500">Sources</p>
          <p className="mt-0.5 font-mono text-sm text-mist-100">{run.source_count}</p>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2">
          <p className="text-[0.62rem] uppercase tracking-wider text-mist-500">Elapsed</p>
          <p className="mt-0.5 font-mono text-sm text-mist-100">{formatElapsed(elapsed)}</p>
        </div>
      </div>

      <div className="mt-4 flex items-start gap-3">
        <div className="pt-0.5">
          <AgentFace size={34} active={running && !stale} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="hud-label">
            <span className="glow-dot" />
            agent mission log
          </p>
          <p className={`mt-1 text-sm ${failed ? "text-danger" : "text-mist-300"}`}>
            {run.message}
            {running && !stale ? (
              <span className="agent-caret ml-1 inline-block h-3 w-1.5 bg-accent/80 align-[-2px]" />
            ) : null}
          </p>
        </div>
      </div>

      {queries.length > 0 || gaps.length > 0 ? (
        <div className="mt-3">
          <EventChips queries={queries} gaps={gaps} />
        </div>
      ) : null}

      {log.length > 0 ? (
        <div className="mt-4 border-t border-ink-700 pt-3">
          <p className="hud-label">
            <span className={`glow-dot ${running ? "" : "opacity-40"}`} />
            live trace
          </p>
          <ul className="mt-2 space-y-1">
            {log.map((event, index) => (
              <li
                key={`${event.stage}-${event.at ?? "ev"}-${index}`}
                className="flex items-baseline gap-2 font-mono text-[0.68rem] text-mist-500"
              >
                <span className="shrink-0 text-mist-500/60">{timestamp(event.at)}</span>
                <span className={`min-w-0 ${index === 0 ? "text-mist-300" : ""}`}>
                  {describeEvent(event)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {run.error ? (
        <div className="mt-4 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2.5 text-xs leading-relaxed text-danger">
          {run.error}
        </div>
      ) : null}
    </section>
  );
}
