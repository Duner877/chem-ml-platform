/** Run output drawer — the ComfyUI-style "queue / output" panel.
 *
 * ComfyUI shows what happened to a run where you can act on it: a queue entry
 * with progress, a per-node timeline, and the artefacts it produced.  This
 * panel is that idea for a node-graph editor:
 *
 *  - header: run id, status pill, wall-clock duration, node tally;
 *  - a live elapsed timer plus progress bar while a run is in flight;
 *  - one row per node: status, human duration, progress, error text and logs;
 *  - the artefact list, each entry a real download link.
 *
 * Before this existed the only place a failure surfaced was the console
 * drawer, which is closed by default -- a broken run looked like nothing had
 * happened at all.
 */

import { useEffect, useRef, useState } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { NodeRecord } from "../types";
import {
  IconAlert,
  IconCheck,
  IconChevron,
  IconClock,
  IconDownload,
  IconImage,
  IconSparkle,
  IconTerminal,
} from "../components/Icons";

/** Render a duration the way a person reads it: ms under a second, else s/min. */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = (ms % 60_000) / 1000;
  return `${minutes}m ${seconds.toFixed(0)}s`;
}

/** A ticking stopwatch so a long run visibly progresses instead of freezing. */
function useElapsed(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const started = useRef<number>(0);

  useEffect(() => {
    if (!active) return;
    started.current = performance.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(performance.now() - started.current),
      100
    );
    return () => window.clearInterval(timer);
  }, [active]);

  return elapsed;
}

const STATUS_STYLE: Record<string, string> = {
  completed: "bg-good/15 text-good",
  running: "bg-accent/15 text-accent",
  failed: "bg-bad/15 text-bad",
  skipped: "bg-panel2 text-[rgb(var(--c-text-dim))]",
  idle: "bg-panel2 text-[rgb(var(--c-text-dim))]",
};

function statusLabel(lang: "zh" | "en", status: string): string {
  switch (status) {
    case "completed":
      return translate(lang, "outCompleted");
    case "running":
      return translate(lang, "running");
    case "failed":
      return translate(lang, "failed");
    case "skipped":
      return translate(lang, "outSkipped");
    default:
      return translate(lang, "idle");
  }
}

/** A single node row: status, duration, progress, error and logs. */
function NodeRow({ record, lang }: { record: NodeRecord; lang: "zh" | "en" }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = Boolean(record.error) || (record.logs?.length ?? 0) > 0;
  const progress =
    typeof record.progress === "number"
      ? record.progress > 1
        ? record.progress / 100
        : record.progress
      : record.status === "completed"
        ? 1
        : 0;
  const pct = Math.max(0, Math.min(1, progress)) * 100;

  return (
    <li className="border-b border-line last:border-b-0">
      <div className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${
            STATUS_STYLE[record.status] ?? STATUS_STYLE.idle
          }`}
        >
          {statusLabel(lang, record.status)}
        </span>

        <span className="min-w-0 flex-1 truncate font-mono text-[rgb(var(--c-text))]">
          {record.node_id}
        </span>

        {record.cached && (
          <span className="rounded bg-panel2 px-1.5 py-0.5 text-[9px] text-[rgb(var(--c-text-dim))]">
            {translate(lang, "outCached")}
          </span>
        )}

        <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
          <IconClock size={11} />
          {formatDuration(record.duration_ms)}
        </span>

        {hasDetail && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            title={translate(lang, "outDetails")}
            className="shrink-0 rounded p-0.5 text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
          >
            <IconChevron size={12} className={expanded ? "rotate-90" : undefined} />
          </button>
        )}
      </div>

      {/* progress bar: real when the node reports it, full when it completed */}
      <div className="h-px w-full bg-line">
        <div
          className={`h-px transition-[width] duration-300 ${
            record.status === "failed"
              ? "bg-bad"
              : record.status === "completed"
                ? "bg-good"
                : "bg-accent"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {expanded && (
        <div className="space-y-1 px-3 pb-2 pt-1">
          {record.error && (
            <p className="flex items-start gap-1.5 rounded bg-bad/10 px-2 py-1 font-mono text-[10px] leading-relaxed text-bad">
              <IconAlert size={11} className="mt-0.5 shrink-0" />
              <span className="break-words">{record.error}</span>
            </p>
          )}
          {(record.logs ?? []).map((line, index) => (
            <p
              key={index}
              className="break-words font-mono text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]"
            >
              {line}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}

export default function OutputPanel() {
  const { lang, runResult, busy, nodes } = useEditor();
  const elapsed = useElapsed(busy);

  const records = Object.values(runResult?.records ?? {});
  const done = records.filter((r) => r.status === "completed").length;
  const failed = records.filter((r) => r.status === "failed").length;
  const artifacts = runResult?.artifacts ?? [];

  // While running we cannot know the true percentage -- the inline endpoint
  // answers only when the whole graph is finished -- so the bar stays
  // indeterminate rather than inventing a number.
  const total = runResult?.nodes ?? nodes.length;

  return (
    <section className="flex h-full flex-col bg-panel">
      {/* header ------------------------------------------------------------ */}
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2 text-[11px]">
        <span className="flex items-center gap-1.5 font-semibold text-[rgb(var(--c-text))]">
          <IconTerminal size={13} />
          {translate(lang, "outputs")}
        </span>

        {busy ? (
          <span className="flex items-center gap-1.5 rounded bg-accent/15 px-2 py-0.5 text-accent">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            {translate(lang, "outRunning")} {formatDuration(elapsed)}
          </span>
        ) : runResult ? (
          <>
            <span
              className={`rounded px-2 py-0.5 ${
                runResult.status === "completed"
                  ? "bg-good/15 text-good"
                  : runResult.status === "failed"
                    ? "bg-bad/15 text-bad"
                    : "bg-warn/15 text-warn"
              }`}
            >
              {runResult.status === "completed"
                ? translate(lang, "outCompleted")
                : runResult.status === "failed"
                  ? translate(lang, "failed")
                  : runResult.status}
            </span>
            <span className="font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
              {runResult.run_id}
            </span>
            <span className="flex items-center gap-1 font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
              <IconClock size={11} />
              {formatDuration(runResult.duration_ms)}
            </span>
            <span className="font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
              {done}/{total} {translate(lang, "outNodes")}
            </span>
            {failed > 0 && (
              <span className="font-mono text-[10px] text-bad">
                {failed} {translate(lang, "outFailed")}
              </span>
            )}
          </>
        ) : (
          <span className="text-[rgb(var(--c-text-faint))]">
            {translate(lang, "outNoRun")}
          </span>
        )}
      </header>

      {/* indeterminate progress strip while a run is in flight --------------- */}
      {busy && (
        <div className="h-0.5 w-full shrink-0 overflow-hidden bg-line">
          <div className="h-full w-1/3 animate-pulse bg-accent" />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* artefacts ------------------------------------------------------- */}
        {artifacts.length > 0 && (
          <div className="border-b border-line">
            <h3 className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] uppercase tracking-wide text-[rgb(var(--c-text-faint))]">
              <IconImage size={11} />
              {translate(lang, "outArtifacts")} ({artifacts.length})
            </h3>
            <ul className="pb-1">
              {artifacts.map((path) => (
                <li key={path}>
                  <a
                    href={`/api/runs/artifacts/${path}`}
                    download
                    className="flex items-center gap-2 px-3 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
                  >
                    <IconDownload size={12} className="shrink-0" />
                    <span className="min-w-0 flex-1 truncate font-mono">{path}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* per-node timeline ------------------------------------------------ */}
        {records.length > 0 ? (
          <ul>
            {records.map((record) => (
              <NodeRow key={record.node_id} record={record} lang={lang} />
            ))}
          </ul>
        ) : (
          !busy && (
            <div className="flex flex-col items-center justify-center gap-1.5 px-4 py-8 text-center">
              <IconSparkle size={16} className="text-[rgb(var(--c-text-faint))]" />
              <p className="text-[11px] text-[rgb(var(--c-text-faint))]">
                {translate(lang, "outNoRun")}
              </p>
            </div>
          )
        )}
      </div>
    </section>
  );
}