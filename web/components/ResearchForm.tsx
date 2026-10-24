"use client";

import { useEffect, useRef, useState } from "react";

import type { StartRunPayload } from "@/lib/types";

const FALLBACK_MODEL_SUGGESTIONS = [
  "gemini-3.8-flash",
  "gemini-2.5-flash",
  "gemini-2.5-flash-lite",
  "openrouter/free",
];

const STORAGE_KEY = "rd.form";

interface SavedForm {
  topic?: string;
  iterations?: number;
}

interface ResearchFormProps {
  defaultModel: string;
  busy: boolean;
  onSubmit: (payload: StartRunPayload) => void;
}

export function ResearchForm({ defaultModel, busy, onSubmit }: ResearchFormProps) {
  const [topic, setTopic] = useState("");
  const [model, setModel] = useState("");
  const [iterations, setIterations] = useState(2);
  const [touched, setTouched] = useState(false);
  const [restored, setRestored] = useState(false);
  const [modelTouched, setModelTouched] = useState(false);
  const formRef = useRef<HTMLFormElement | null>(null);

  const modelSuggestions = defaultModel.trim()
    ? [defaultModel, ...FALLBACK_MODEL_SUGGESTIONS.filter((item) => item !== defaultModel)]
    : FALLBACK_MODEL_SUGGESTIONS;

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        setTopic("small language models");
        setRestored(true);
        return;
      }
      const saved = JSON.parse(raw) as SavedForm;
      if (typeof saved.topic === "string" && saved.topic.trim()) setTopic(saved.topic);
      if (
        typeof saved.iterations === "number" &&
        Number.isInteger(saved.iterations) &&
        saved.iterations >= 1 &&
        saved.iterations <= 5
      ) {
        setIterations(saved.iterations);
      }
    } catch {
      // ignore corrupted settings
    }
    setRestored(true);
  }, []);

  useEffect(() => {
    if (!restored || modelTouched) return;
    setModel("");
  }, [defaultModel, modelTouched, restored]);

  useEffect(() => {
    if (!restored) return;
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ topic, iterations } satisfies SavedForm),
      );
    } catch {
      // storage may be unavailable (private mode)
    }
  }, [iterations, restored, topic]);

  const cleaned = topic.replace(/\s+/g, " ").trim();
  const valid = cleaned.length >= 3 && cleaned.length <= 300;

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    onSubmit({
      topic: cleaned,
      model: model.trim() || undefined,
      max_iterations: iterations,
    });
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit} className="card card-pad">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="hud-label">
            <span className="glow-dot" />
            new task
          </p>
          <h2 className="mt-0.5 text-sm font-semibold tracking-wide text-mist-100">
            Brief the agent
          </h2>
        </div>
        <span className="font-mono text-[0.65rem] uppercase tracking-[0.14em] text-mist-500">
          agent graph
        </span>
      </div>

      <div className="mt-5">
        <div className="flex items-baseline justify-between">
          <label htmlFor="topic" className="label">
            Topic
          </label>
          <span className="font-mono text-[0.62rem] text-mist-500">⌘/Ctrl + ↵ to run</span>
        </div>
        <textarea
          id="topic"
          name="topic"
          rows={3}
          value={topic}
          maxLength={300}
          onChange={(event) => setTopic(event.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={() => setTouched(true)}
          placeholder="e.g. small language models for on-device inference"
          className="field resize-none"
          aria-invalid={touched && !valid}
          aria-describedby="topic-help"
        />
        <div id="topic-help" className="mt-1.5 flex items-center justify-between text-xs">
          <span className={touched && !valid ? "text-danger" : "text-mist-500"}>
            {touched && !valid ? "Enter at least 3 characters." : "The agent works best on specific topics."}
          </span>
          <span className="font-mono text-mist-500">{cleaned.length}/300</span>
        </div>
      </div>

      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <label htmlFor="model" className="label">
            Model
          </label>
          <span className="font-mono text-[0.62rem] text-mist-500">agent default applies</span>
        </div>
        <input
          id="model"
          name="model"
          list="model-options"
          value={model}
          onChange={(event) => {
            setModel(event.target.value);
            setModelTouched(true);
          }}
          placeholder={defaultModel || "gemini-3.5-flash-lite"}
          className="field font-mono text-[0.82rem]"
          spellCheck={false}
        />
        <datalist id="model-options">
          {modelSuggestions.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
        <p className="mt-1.5 text-xs text-mist-500">
          Leave empty to run the agent default{" "}
          <span className="font-mono text-accent-soft/90">
            {defaultModel || "gemini-3.5-flash-lite"}
          </span>{" "}
          (set via <span className="font-mono">AGENT_MODEL</span> in{" "}
          <span className="font-mono">.env</span>). Google Gemini and OpenRouter ids both work; free
          models are rate-limited.
        </p>
      </div>

      <fieldset className="mt-4">
        <legend className="label">Critique rounds</legend>
        <div className="grid grid-cols-5 gap-1.5" role="group" aria-label="Critique rounds">
          {[1, 2, 3, 4, 5].map((count) => (
            <button
              key={count}
              type="button"
              onClick={() => setIterations(count)}
              aria-pressed={iterations === count}
              aria-label={`${count} critique round${count === 1 ? "" : "s"}`}
              className={`rounded-lg border px-1 py-2 text-sm font-medium transition ${
                iterations === count
                  ? "border-accent/70 bg-accent/10 text-accent-soft"
                  : "border-ink-600 bg-ink-950 text-mist-300 hover:bg-ink-800"
              }`}
            >
              {count}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-mist-500">
          More rounds = deeper research and a longer run.
        </p>
      </fieldset>

      <button
        type="submit"
        disabled={busy || !valid}
        className="btn btn-primary mt-5 w-full"
        aria-label="Launch the research agent"
      >
        {busy ? (
          <>
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#101505]/30 border-t-[#101505]" />
            Launching agent…
          </>
        ) : (
          <>
            Launch agent
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M3.5 8h9m0 0L8.75 4.25M12.5 8l-3.75 3.75"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </>
        )}
      </button>
      <p className="mt-3 text-center text-xs text-mist-500">
        Typical run takes 1–3 minutes. Keep this tab open to watch progress.
      </p>
    </form>
  );
}
