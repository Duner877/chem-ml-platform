/** Console drawer: run status, per-node records, artefacts and logs. */

import { useEffect, useRef } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { RunResult } from "../types";

function statusColor(status: string): string {
  if (status === "completed") return "text-good";
  if (status === "failed") return "text-bad";
  if (status === "skipped") return "text-slate-500";
  return "text-warn";
}

function RunSummary({ result }: { result: RunResult }) {
  const { lang } = useEditor();
  const records = Object.values(result.records ?? {});
  return (
    <div className="border-b border-line px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <span className={`font-semibold ${statusColor(result.status)}`}>
          {result.status}
        </span>
        <span className="text-slate-400">
          {result.nodes} {translate(lang, "nodes")}
        </span>
        <span className="text-slate-400">
          {translate(lang, "duration")} {result.duration_ms.toFixed(0)} ms
        </span>
        <span className="text-slate-400">
          {translate(lang, "artifacts")}: {result.artifacts.length}
        </span>
        {result.errors.length > 0 && (
          <span className="text-bad">
            {translate(lang, "errors")}: {result.errors.length}
          </span>
        )}
      </div>
      <div className="mt-1 max-h-24 overflow-y-auto">
        {records.map((record) => (
          <div key={record.node_id} className="flex gap-2 text-[10px]">
            <span className="w-40 shrink-0 truncate font-mono text-slate-300">
              {record.node_id}
            </span>
            <span className={`w-20 shrink-0 ${statusColor(record.status)}`}>
              {record.status}
            </span>
            <span className="shrink-0 text-slate-500">
              {record.duration_ms.toFixed(1)} ms
            </span>
            {record.error && (
              <span className="truncate text-bad">{record.error}</span>
            )}
          </div>
        ))}
      </div>
      {result.artifacts.length > 0 && (
        <div className="mt-1 max-h-16 overflow-y-auto">
          {result.artifacts.map((path) => (
            <a
              key={path}
              href={`/api/runs/artifacts/${path}`}
              target="_blank"
              rel="noreferrer"
              className="block truncate font-mono text-[10px] text-accent/80 hover:text-accent hover:underline"
            >
              ⤓ {path.split(/[\\/]/).slice(-2).join("/")}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Console() {
  const { logs, runResult, status, lang, setConsoleOpen, pushLog } = useEditor();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [logs]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-1.5">
        <span className="text-[10px] text-[rgb(var(--c-text-faint))]">
          {status} · {logs.length} {translate(lang, "logs")}
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => {
            // Clearing the log list keeps the store honest: no hidden state.
            useEditor.setState({ logs: [] });
            pushLog(`$ ${translate(lang, "clearLogs")}`);
          }}
          className="rounded px-2 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          {translate(lang, "clearLogs")}
        </button>
        <button
          type="button"
          onClick={() => setConsoleOpen(false)}
          className="rounded px-2 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          ✕ {translate(lang, "close")}
        </button>
      </div>

      {runResult && <RunSummary result={runResult} />}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-relaxed">
        {logs.length === 0 ? (
          <p className="text-[rgb(var(--c-text-faint))]">{translate(lang, "idle")}</p>
        ) : (
          logs.map((line, index) => (
            <div key={index} className="whitespace-pre-wrap break-all text-slate-300">
              {line}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
