"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AgentFace } from "@/components/AgentFace";
import { AgentNodeMap } from "@/components/AgentNodeMap";
import { DigestView } from "@/components/DigestView";
import { GitHubPanel } from "@/components/GitHubPanel";
import { RecentRuns } from "@/components/RecentRuns";
import { ResearchForm } from "@/components/ResearchForm";
import { RunProgress } from "@/components/RunProgress";
import { api, ApiError } from "@/lib/api";
import { bootstrapFromHash, GITHUB_MODE, takeAutoRun } from "@/lib/github";
import type { Health, ResearchRun, RunSummary, StartRunPayload } from "@/lib/types";

if (typeof window !== "undefined") bootstrapFromHash();

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

function HealthPill({ health, offline }: { health: Health | null; offline: boolean }) {
  if (offline) {
    return (
      <span className="chip border-danger/40 text-danger">
        <span className="h-1.5 w-1.5 rounded-full bg-danger" />
        API offline
      </span>
    );
  }
  if (!health) {
    return (
      <span className="chip">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-mist-500" />
        Checking API
      </span>
    );
  }
  if (health.fake_model) {
    return (
      <span className="chip border-warn/40 text-warn">
        <span className="h-1.5 w-1.5 rounded-full bg-warn" />
        Offline demo
      </span>
    );
  }
  if (!health.has_api_key) {
    return (
      <span className="chip border-warn/40 text-warn">
        <span className="h-1.5 w-1.5 rounded-full bg-warn" />
        API key missing
      </span>
    );
  }
  return (
    <span className="chip border-accent/40 text-accent-soft">
      <span className="h-1.5 w-1.5 rounded-full bg-accent" />
      Live · {health.default_model}
    </span>
  );
}

function OfflineNotice() {
  return (
    <div className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-xs leading-relaxed text-mist-300">
      <p className="font-semibold text-danger">The FastAPI server is not reachable.</p>
      <p className="mt-1">Start it from the project root, then reload this page:</p>
      <code className="mt-2 block overflow-x-auto rounded bg-ink-950 px-2 py-1.5 font-mono text-[0.7rem] text-accent-soft">
        uv run uvicorn research_agent.api:app --reload --port 8000
      </code>
      <p className="mt-2">
        Current API URL: <span className="font-mono">{api.baseUrl}</span>. Override it with{" "}
        <span className="font-mono">NEXT_PUBLIC_API_URL</span> in{" "}
        <span className="font-mono">web/.env.local</span>.
      </p>
    </div>
  );
}

function FlowLink({ active }: { active: boolean }) {
  return (
    <div className="relative hidden pt-[7.75rem] lg:flex" aria-hidden="true">
      <div className="relative flex h-6 w-full items-center">
        <span className="h-px w-full bg-gradient-to-r from-accent/10 via-accent/35 to-accent/70" />
        <span className="absolute right-0 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rotate-45 border-r border-t border-accent/70" />
        {active ? <span className="flow-dot" /> : null}
      </div>
    </div>
  );
}

function OutputIdle() {
  return (
    <section className="card hud card-pad" aria-hidden="true">
      <p className="hud-label">
        <span className="glow-dot opacity-40" />
        output stream
      </p>
      <div className="flex flex-col items-center gap-3 py-12 text-center">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" className="text-mist-500/50">
          <path d="M6 3h9l4 4v14H6z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          <path d="M15 3v4h4M9 12h7M9 16h7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <p className="text-sm text-mist-500">Awaiting digest…</p>
      </div>
    </section>
  );
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [stale, setStale] = useState(false);
  const pollRef = useRef<number | null>(null);
  const bootRef = useRef(false);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const [listing, status] = await Promise.all([api.listRuns(), api.health()]);
      setRuns(listing.runs);
      setHealth(status);
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (!run) return;
    const active = run.status === "queued" || run.status === "running";
    if (!active) return;
    const runId = run.id;
    let cancelled = false;
    let failures = 0;

    const tick = async () => {
      try {
        const next = await api.getRun(runId);
        if (cancelled) return;
        failures = 0;
        setStale(false);
        setRun(next);
        setOffline(false);
        if (next.status === "succeeded" || next.status === "failed") {
          void refreshRuns();
        } else {
          pollRef.current = window.setTimeout(tick, 1500);
        }
      } catch {
        if (cancelled) return;
        failures += 1;
        if (failures >= 2) setStale(true);
        if (failures >= 4) setOffline(true);
        pollRef.current = window.setTimeout(tick, 3000);
      }
    };

    pollRef.current = window.setTimeout(tick, 600);
    return () => {
      cancelled = true;
      if (pollRef.current !== null) window.clearTimeout(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.status, refreshRuns]);

  async function handleStart(payload: StartRunPayload) {
    setBusy(true);
    setError(null);
    try {
      const created = await api.startRun(payload);
      setRun(created);
      setOffline(false);
      setStale(false);
      void refreshRuns();
      if (typeof window !== "undefined" && window.innerWidth < 1024) {
        window.setTimeout(() => {
          document
            .getElementById("run-panel")
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 80);
      }
    } catch (cause) {
      setError(errorMessage(cause));
      if (cause instanceof ApiError && cause.status === 0) setOffline(true);
    } finally {
      setBusy(false);
    }
  }

  async function handleSelect(id: string) {
    try {
      const selected = await api.getRun(id);
      setRun(selected);
      setError(null);
      setStale(false);
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  useEffect(() => {
    if (bootRef.current) return;
    bootRef.current = true;
    const pending = takeAutoRun();
    if (pending) void handleStart(pending);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const active = run?.status === "queued" || run?.status === "running";
    if (active) return;
    const timer = window.setInterval(() => void refreshHealth(), 30_000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  useEffect(() => {
    const selectedActive = run?.status === "queued" || run?.status === "running";
    if (selectedActive) return;
    const serverActive = runs.some(
      (entry) => entry.status === "queued" || entry.status === "running",
    );
    if (!serverActive) return;
    const timer = window.setInterval(() => void refreshRuns(), 6000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, run?.status]);

  useEffect(() => {
    const base = "Research Agent · sample-research-agent";
    if (!run) {
      document.title = base;
      return;
    }
    const suffix = run.status === "running" || run.status === "queued" ? " (running)" : "";
    document.title = `${run.topic}${suffix} · Research Agent`;
  }, [run?.topic, run?.status]);

  const agentActive = run?.status === "running" || run?.status === "queued";

  return (
    <main className="mx-auto w-full max-w-7xl px-4 pb-16 pt-8 md:px-6 md:pt-12">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <AgentFace size={42} active={agentActive} />
          <div>
            <h1 className="text-glow text-xl font-semibold tracking-tight text-mist-100">
              Research Agent
            </h1>
            <p className="text-xs text-mist-500">
              Autonomous web researcher · LangGraph · FastAPI · Next.js
            </p>
          </div>
        </div>
        <HealthPill health={health} offline={offline} />
      </header>

      <div className="mt-6 space-y-3">
        {error ? (
          <div className="flex items-start justify-between gap-3 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-xs leading-relaxed text-mist-300">
            <p>
              <span className="font-semibold text-danger">Something went wrong. </span>
              {error}
            </p>
            <button
              type="button"
              onClick={() => setError(null)}
              aria-label="Dismiss error"
              className="shrink-0 rounded p-1 text-mist-500 transition hover:text-mist-100"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M4 4l8 8m0-8-8 8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        ) : null}
        {offline && !run ? <OfflineNotice /> : null}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,0.95fr)_30px_minmax(0,1.35fr)_30px_minmax(0,1.1fr)] lg:items-start lg:gap-x-0">
        <div className="space-y-5 lg:sticky lg:top-8">
          <ResearchForm
            defaultModel={health?.default_model ?? "gemini-3.5-flash-lite"}
            busy={busy}
            onSubmit={handleStart}
          />
          {GITHUB_MODE ? <GitHubPanel /> : null}
          <RecentRuns
            runs={runs}
            activeId={run?.id ?? null}
            loading={loadingHistory}
            onSelect={handleSelect}
            onRefresh={refreshRuns}
          />
        </div>

        <FlowLink active={agentActive} />

        <div className="space-y-5" id="run-panel">
          <AgentNodeMap run={run} />
          {run ? <RunProgress run={run} stale={stale} /> : null}
        </div>

        <FlowLink active={agentActive} />

        <div className="space-y-5">
          {run ? <DigestView run={run} /> : <OutputIdle />}
        </div>
      </div>

      <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-ink-700 pt-5 text-[0.7rem] text-mist-500">
        <p>
          Backend: <span className="font-mono">{api.baseUrl}</span>
        </p>
        <p>
          Runs are held in server memory. Digests are written to{" "}
          <span className="font-mono">reports/</span>.
        </p>
      </footer>
    </main>
  );
}
