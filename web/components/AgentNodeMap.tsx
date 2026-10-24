"use client";

import Image from "next/image";
import type { ReactNode } from "react";

import type { ResearchRun } from "@/lib/types";

type NodeState = "idle" | "active" | "done" | "failed";

interface NodeDef {
  key: string;
  label: string;
  hint: string;
  icon: ReactNode;
}

function PlanIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="3" y="2.5" width="10" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ResearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="7" cy="7" r="4.2" stroke="currentColor" strokeWidth="1.4" />
      <path d="m10.2 10.2 3.2 3.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function CritiqueIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2.5 4.6l.9 1 1.6-1.9M7.2 4.7h6.3M2.5 8l.9 1 1.6-1.9M7.2 8.1h6.3M2.5 11.4l.9 1 1.6-1.9M7.2 11.5h4.4"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function WriteIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M3 13l.7-2.6 6.6-6.6 1.9 1.9-6.6 6.6L3 13z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path d="M8.9 4.7l2 2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function VerifyIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 2.4l4.9 1.8v3.9c0 2.8-2.1 4.6-4.9 5.5-2.8-.9-4.9-2.7-4.9-5.5V4.2L8 2.4z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <path
        d="M5.8 7.9l1.5 1.5 2.9-3.1"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SaveIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <ellipse cx="8" cy="4" rx="4.4" ry="1.8" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M3.6 4v8c0 1 2 1.8 4.4 1.8s4.4-.8 4.4-1.8V4"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path d="M3.6 8c0 1 2 1.8 4.4 1.8s4.4-.8 4.4-1.8" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  );
}

const NODES: NodeDef[] = [
  { key: "plan", label: "Plan", hint: "frame questions", icon: <PlanIcon /> },
  { key: "research", label: "Search + Read", hint: "web + pages", icon: <ResearchIcon /> },
  { key: "critique", label: "Critique", hint: "find gaps", icon: <CritiqueIcon /> },
  { key: "write", label: "Write", hint: "synthesize", icon: <WriteIcon /> },
  { key: "verify", label: "Verify", hint: "fact-check", icon: <VerifyIcon /> },
  { key: "save", label: "Save", hint: "store digest", icon: <SaveIcon /> },
];

const STAGE_INDEX: Record<string, number> = {
  queued: -1,
  starting: 0,
  plan: 0,
  research: 1,
  tools: 1,
  fetch: 1,
  critique: 2,
  write: 3,
  verify: 4,
  save: 5,
  done: 6,
};

const TILE_CLASSES: Record<NodeState, string> = {
  idle: "border-ink-700 bg-ink-950/60",
  active: "border-accent/60 bg-accent/10 shadow-[0_0_24px_-8px_rgba(34,211,238,0.55)]",
  done: "border-accent/25 bg-ink-850/80",
  failed: "border-danger/50 bg-danger/5",
};

const ICON_CLASSES: Record<NodeState, string> = {
  idle: "text-mist-500",
  active: "text-accent",
  done: "text-accent-soft/90",
  failed: "text-danger",
};

const LABEL_CLASSES: Record<NodeState, string> = {
  idle: "text-mist-300",
  active: "text-accent-soft",
  done: "text-mist-100",
  failed: "text-danger",
};

function StatusMark({ state }: { state: NodeState }) {
  if (state === "done") {
    return (
      <span
        className="grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border border-accent/40 bg-accent/10 text-accent"
        aria-hidden="true"
      >
        <svg width="8" height="8" viewBox="0 0 16 16" fill="none">
          <path
            d="M3.5 8.5l3 3 6-7"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span
        className="grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border border-danger/50 bg-danger/10 text-danger"
        aria-hidden="true"
      >
        <svg width="7" height="7" viewBox="0 0 16 16" fill="none">
          <path d="M5 5l6 6m0-6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  if (state === "active") {
    return <span className="pulse-dot h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden="true" />;
  }
  return <span className="h-2 w-2 shrink-0 rounded-full border border-mist-500/50" aria-hidden="true" />;
}

export function AgentNodeMap({ run }: { run: ResearchRun | null }) {
  const succeeded = run?.status === "succeeded";
  const failed = run?.status === "failed";
  const running = run?.status === "queued" || run?.status === "running";
  const lastStage = run
    ? [...run.events].reverse().find((event) => event.stage !== "failed")?.stage
    : undefined;
  const current = !run ? -1 : succeeded ? NODES.length : (STAGE_INDEX[lastStage ?? run.stage] ?? 0);
  const failIndex = failed ? (STAGE_INDEX[lastStage ?? run.stage] ?? 0) : -1;

  function stateFor(index: number): NodeState {
    if (!run) return "idle";
    if (failed) {
      if (index === failIndex) return "failed";
      return index < failIndex ? "done" : "idle";
    }
    if (succeeded) return "done";
    if (index < current) return "done";
    if (index === current) return "active";
    return "idle";
  }

  const statusLabel = !run
    ? "standing by"
    : failed
      ? "halted"
      : succeeded
        ? "mission complete"
        : run.status === "queued"
          ? "queued"
          : `${NODES[Math.max(0, Math.min(current, NODES.length - 1))].label.toLowerCase()}…`;

  return (
    <section className="card hud overflow-hidden" aria-label="Research agent node graph">
      <div className="flex items-center justify-between gap-2 px-4 pt-4">
        <p className="hud-label text-accent-soft!">
          <span className="glow-dot" />
          sys.core // research-agent
        </p>
        <p className="hud-label text-mist-300!">neural link · online</p>
      </div>

      <div className="px-4 pb-4 pt-3">
        <div className="flex flex-col items-center">
          <div
            className="avatar-core"
            style={{
              width: 148,
              height: 148,
              borderRadius: "50%",
              boxShadow: running
                ? "0 0 40px rgba(34, 211, 238, 0.35)"
                : "0 0 22px rgba(34, 211, 238, 0.16)",
            }}
          >
            <span className="relative z-[1] block h-full w-full overflow-hidden rounded-full border border-accent/30 bg-ink-900">
              <Image
                src="/agentic-ai.jpg"
                alt="The research agent"
                width={735}
                height={490}
                priority
                className="h-full w-full object-cover"
                style={{
                  objectPosition: "50% 42%",
                  transform: "scale(1.6)",
                  transformOrigin: "50% 40%",
                }}
              />
            </span>
          </div>
          <span className="hud-label mt-2">
            <span className={`glow-dot ${running ? "" : "opacity-40"}`} />
            {statusLabel}
          </span>
        </div>

        <div className="relative mx-auto mt-3 h-4 w-px bg-gradient-to-b from-accent/50 via-accent/25 to-ink-700" aria-hidden="true">
          <span
            className={`absolute -left-[2px] top-1/2 h-1 w-1 -translate-y-1/2 rounded-full ${
              running ? "bg-accent pulse-dot" : "bg-ink-600"
            }`}
          />
        </div>

        <div className="mt-2 grid grid-cols-2 gap-2">
          {NODES.map((node, index) => {
            const state = stateFor(index);
            return (
              <div
                key={node.key}
                title={node.hint}
                className={`relative flex items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors ${TILE_CLASSES[state]}`}
              >
                <span
                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-md border border-ink-700 bg-ink-950/70 ${ICON_CLASSES[state]}`}
                >
                  {node.icon}
                </span>
                <span
                  className={`min-w-0 flex-1 truncate text-[0.66rem] font-semibold ${LABEL_CLASSES[state]}`}
                >
                  {node.label}
                </span>
                <StatusMark state={state} />
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
