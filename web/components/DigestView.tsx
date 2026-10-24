"use client";

import { useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatElapsed, hostnameOf, stripFrontmatter } from "@/lib/api";
import type { ResearchRun } from "@/lib/types";

const markdownComponents: Components = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: ({ node: _node, ...props }) => (
    <div className="overflow-x-auto">
      <table {...props} />
    </div>
  ),
};

function Skeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      <div className="shimmer h-5 w-2/3 rounded" />
      <div className="shimmer h-3 w-full rounded" />
      <div className="shimmer h-3 w-11/12 rounded" />
      <div className="shimmer h-3 w-4/5 rounded" />
      <div className="shimmer mt-6 h-4 w-1/3 rounded" />
      <div className="shimmer h-3 w-full rounded" />
      <div className="shimmer h-3 w-10/12 rounded" />
    </div>
  );
}

function FailureNote({ error }: { error: string | null }) {
  return (
    <div
      className="rounded-xl border border-danger/25 bg-danger/5 px-4 py-3.5 text-xs leading-relaxed text-mist-300"
      role="alert"
    >
      <p className="text-sm font-semibold text-danger">
        The run failed before a digest was written.
      </p>
      {error ? <p className="mt-2 break-words text-mist-300">{error}</p> : null}
      <p className="mt-2 text-mist-500">
        Free models rate-limit often. Try another model id, fewer critique rounds, or
        run again in a minute.
      </p>
    </div>
  );
}

function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

export function DigestView({ run }: { run: ResearchRun }) {
  const [copied, setCopied] = useState(false);
  const articleRef = useRef<HTMLElement | null>(null);
  const body = stripFrontmatter(run.report);
  const ready = run.status === "succeeded" && body.length > 0;
  const failed = run.status === "failed" && !ready;

  const headings = body
    .split("\n")
    .filter((line) => line.startsWith("## ") && !line.startsWith("### "))
    .map((line) => line.replace(/^##\s+/, "").trim());

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(body);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  function handleDownload() {
    const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const name = run.output_path.split(/[\\/]/).pop() ?? `${run.id}-digest.md`;
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function scrollToHeading(index: number) {
    const target = articleRef.current?.querySelectorAll("h2")[index];
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const words = countWords(body);
  const readingMinutes = Math.max(1, Math.round(words / 200));

  return (
    <section className="card card-pad">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[0.65rem] uppercase tracking-[0.16em] text-mist-500">
            Agent output
          </p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight text-mist-100">
            {ready ? "Agent report" : failed ? "No report generated" : "The agent is drafting"}
          </h2>
        </div>
        {ready ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleCopy}
              className="btn btn-ghost"
              aria-label="Copy the report as markdown to the clipboard"
            >
              {copied ? "Copied ✓" : "Copy markdown"}
            </button>
            <button type="button" onClick={handleDownload} className="btn btn-ghost">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path
                  d="M8 2v8m0 0 3-3m-3 3L5 7M3 12.5h10"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Download
            </button>
          </div>
        ) : null}
      </div>

      {failed ? null : (
        <div className="mt-4 flex flex-wrap gap-1.5">
          <span className="chip">{run.source_count} sources</span>
          <span className="chip">
            {run.rounds} critique {run.rounds === 1 ? "round" : "rounds"}
          </span>
          <span className="chip">{formatElapsed(run.elapsed_seconds)}</span>
          {ready && words > 0 ? (
            <span className="chip">
              {words.toLocaleString()} words · ~{readingMinutes} min read
            </span>
          ) : null}
          {run.usage?.total_tokens ? (
            <span className="chip">{run.usage.total_tokens.toLocaleString()} tokens</span>
          ) : null}
          <span className="chip font-mono">{run.model}</span>
        </div>
      )}

      <div className="mt-6">
        {ready ? (
          <>
            {headings.length >= 2 ? (
              <nav aria-label="Sections" className="mb-5 flex flex-wrap gap-1.5">
                {headings.map((heading, index) => (
                  <button
                    key={index}
                    type="button"
                    onClick={() => scrollToHeading(index)}
                    className="rounded-full border border-ink-600 bg-ink-950 px-2.5 py-1 text-[0.7rem] text-mist-300 transition hover:border-accent/50 hover:text-accent-soft"
                  >
                    {heading}
                  </button>
                ))}
              </nav>
            ) : null}
            <article ref={articleRef} className="digest">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {body}
              </ReactMarkdown>
            </article>
          </>
        ) : failed ? (
          <FailureNote error={run.error} />
        ) : (
          <Skeleton />
        )}
      </div>

      {ready && run.sources.length > 0 ? (
        <details className="group mt-6 border-t border-ink-700 pt-4">
          <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold text-mist-300">
            <span>Sources the agent collected ({run.sources.length})</span>
            <span className="font-mono text-[0.65rem] text-mist-500 group-open:hidden">
              show
            </span>
            <span className="hidden font-mono text-[0.65rem] text-mist-500 group-open:inline">
              hide
            </span>
          </summary>
          <ul className="mt-3 space-y-2">
            {run.sources.map((source) => (
              <li key={source.url} className="flex items-start gap-2 text-xs">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent/70" />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-mist-300 underline decoration-ink-600 underline-offset-2 hover:text-accent-soft"
                    >
                      {source.title || source.url}
                    </a>
                    <span
                      className={`font-mono text-[0.58rem] uppercase tracking-wider ${
                        source.kind === "page"
                          ? "rounded bg-accent/10 px-1 py-0.5 text-accent-soft"
                          : "text-mist-500"
                      }`}
                    >
                      {source.kind === "page" ? "read" : "search"}
                    </span>
                  </div>
                  <p className="truncate font-mono text-[0.65rem] text-mist-500">
                    {hostnameOf(source.url)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {run.output_path && !failed ? (
        <p className="mt-4 truncate border-t border-ink-700 pt-3 font-mono text-[0.65rem] text-mist-500">
          saved to {run.output_path}
        </p>
      ) : null}
    </section>
  );
}
