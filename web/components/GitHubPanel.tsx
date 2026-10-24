"use client";

import { useEffect, useState } from "react";

import { ghActionsUrl, readToken, writeToken } from "@/lib/github";

export function GitHubPanel() {
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const stored = readToken();
    setToken(stored);
    setSaved(Boolean(stored));
  }, []);

  function save() {
    writeToken(token);
    setSaved(Boolean(token.trim()));
  }

  return (
    <section className="card card-pad hud">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="hud-label">
            <span className="glow-dot" />
            cloud runner
          </p>
          <h2 className="mt-0.5 text-sm font-semibold tracking-wide text-mist-100">
            GitHub Actions
          </h2>
        </div>
        <span
          className={`chip ${
            saved ? "border-accent/40 text-accent-soft" : "border-warn/40 text-warn"
          }`}
        >
          <span
            className={`h-1.5 w-1.5 rounded-full ${saved ? "bg-accent" : "bg-warn"}`}
            aria-hidden="true"
          />
          {saved ? "Connected" : "Token needed"}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-mist-500">
        Runs execute on GitHub Actions — no other server involved. The token stays in this browser
        only.
      </p>

      <div className="mt-3">
        <label htmlFor="gh-token" className="label">
          Fine-grained token
        </label>
        <div className="mt-1 flex gap-2">
          <input
            id="gh-token"
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            onBlur={save}
            placeholder="github_pat_..."
            autoComplete="off"
            spellCheck={false}
            className="field font-mono text-[0.75rem]"
          />
          <button
            type="button"
            onClick={save}
            className="shrink-0 rounded-lg border border-accent/40 bg-accent/10 px-3 text-xs font-semibold text-accent-soft transition hover:bg-accent/15"
          >
            Save
          </button>
        </div>
        <p className="mt-1.5 text-[0.65rem] leading-relaxed text-mist-500">
          Needs <span className="font-mono">Actions: read and write</span> and{" "}
          <span className="font-mono">Contents: read</span> on this repo.{" "}
          <a
            href="https://github.com/settings/personal-access-tokens/new"
            target="_blank"
            rel="noreferrer"
            className="text-accent-soft underline decoration-accent/30 hover:decoration-accent"
          >
            Create token
          </a>
          {" · "}
          <a
            href={ghActionsUrl()}
            target="_blank"
            rel="noreferrer"
            className="text-accent-soft underline decoration-accent/30 hover:decoration-accent"
          >
            View runs
          </a>
        </p>
      </div>
    </section>
  );
}
