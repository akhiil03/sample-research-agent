import type { RunEvent } from "./types";

export function describeEvent(event: RunEvent): string {
  const { stage, status } = event;
  if (stage === "plan") {
    if (status === "started") return "Planning research questions";
    const queries = Array.isArray(event.queries) ? event.queries.length : 0;
    return `Planned ${queries} search ${queries === 1 ? "query" : "queries"}`;
  }
  if (stage === "research") {
    if (status === "started") return "Searching the web";
    const calls = typeof event.tool_calls === "number" ? event.tool_calls : 0;
    if (calls) return `Gathered evidence (${calls} tool ${calls === 1 ? "call" : "calls"})`;
    return `Reviewed evidence (${event.sources ?? 0} sources)`;
  }
  if (stage === "tools") return `Read ${event.results ?? 0} tool results`;
  if (stage === "critique") {
    if (status === "started") return "Critiquing the evidence";
    return event.sufficient ? "Critic satisfied" : "Critic found gaps";
  }
  if (stage === "write") {
    if (status === "started") return "Writing the digest";
    return "Draft complete";
  }
  if (stage === "verify") {
    if (status === "started") return "Verifying the draft";
    if (event.revised) return "Verification found issues; rewriting";
    const dropped = typeof event.dropped === "number" ? event.dropped : 0;
    if (dropped) return `Cleaned ${dropped} bad citation${dropped === 1 ? "" : "s"}`;
    return "Verification passed";
  }
  if (stage === "save") return "Digest saved";
  return `${stage} ${status ?? ""}`.trim();
}
