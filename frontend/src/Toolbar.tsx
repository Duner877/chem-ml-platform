/** Top toolbar: brand, language switch, workflow actions. */

import { useEffect, useState } from "react";
import { useEditor } from "./store";
import { translate } from "./i18n";
import { api } from "./api";
import type { WorkflowSummary } from "./types";

export default function Toolbar() {
  const {
    lang,
    toggleLang,
    nodes,
    edges,
    loadWorkflow,
    clearCanvas,
    resetStatus,
    busy,
    setBusy,
    setNotice,
    pushLog,
    setRunResult,
    setBackend,
    backend,
    setMarketplace,
    setDockTab,
  } = useEditor();

  const [demos, setDemos] = useState<WorkflowSummary[]>([]);

  useEffect(() => {
    api
      .workflows()
      .then(setDemos)
      .catch(() => setDemos([]));
  }, []);

  useEffect(() => {
    api
      .health()
      .then(() => setBackend("online"))
      .catch(() => setBackend("offline"));
  }, [setBackend]);

  function buildPayload() {
    return {
      name: "Editor Workflow",
      nodes: nodes.map((node) => {
        const data = node.data as unknown as {
          type: string;
          label: string;
          params: Record<string, unknown>;
        };
        return {
          id: node.id,
          type: data.type,
          label: data.label,
          params: data.params,
          position: { x: node.position.x, y: node.position.y },
        };
      }),
      edges: edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        source_port: edge.sourceHandle ?? undefined,
        target_port: edge.targetHandle ?? undefined,
      })),
    };
  }

  async function handleRun() {
    resetStatus();
    setBusy(true);
    setRunResult(null);
    pushLog(`$ run workflow (${nodes.length} nodes / ${edges.length} edges)`);
    try {
      const result = await api.runInline(buildPayload());
      setRunResult(result);
      for (const [nodeId, record] of Object.entries(result.records ?? {})) {
        pushLog(
          `[${record.status}] ${nodeId} (${record.duration_ms.toFixed(0)} ms)` +
            (record.error ? ` — ${record.error}` : "")
        );
        for (const line of record.logs ?? []) pushLog(`    ${line}`);
      }
      pushLog(
        result.errors.length
          ? `! ${result.errors.length} node(s) failed`
          : `✔ run ${result.run_id} finished in ${result.duration_ms.toFixed(0)} ms`
      );
      setNotice(result.status);
    } catch (error) {
      pushLog(`! ${(error as Error).message}`);
      setNotice("failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleValidate() {
    try {
      const result = await api.validate(buildPayload());
      pushLog(
        result.valid
          ? "✔ workflow is valid"
          : `✘ ${result.issues.length} issue(s):\n${result.issues.join("\n")}`
      );
      setNotice(result.valid ? "valid" : "invalid");
    } catch (error) {
      pushLog(`! ${(error as Error).message}`);
    }
  }

  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-line bg-panel px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 text-sm font-bold text-accent">
          CML
        </span>
        <div>
          <div className="text-sm font-semibold leading-tight text-slate-100">
            {translate(lang, "title")}
          </div>
          <div className="text-[10px] leading-tight text-slate-500">
            v{__CHEMML_VERSION__} · {translate(lang, "subtitle")}
          </div>
        </div>
      </div>

      <div className="mx-2 h-6 w-px bg-line" />

      <button
        type="button"
        onClick={handleRun}
        disabled={busy || nodes.length === 0}
        className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-canvas transition hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? `${translate(lang, "running")}…` : `▶ ${translate(lang, "run")}`}
      </button>

      <button
        type="button"
        onClick={handleValidate}
        disabled={nodes.length === 0}
        className="rounded-md border border-line px-3 py-1.5 text-xs text-slate-300 transition hover:border-accent disabled:opacity-40"
      >
        {translate(lang, "validate")}
      </button>

      <button
        type="button"
        onClick={() => {
          clearCanvas();
          pushLog("$ clear canvas");
        }}
        className="rounded-md border border-line px-3 py-1.5 text-xs text-slate-300 transition hover:border-bad"
      >
        {translate(lang, "clear")}
      </button>

      <div className="mx-2 h-6 w-px bg-line" />

      <button
        type="button"
        onClick={() => setMarketplace(true)}
        className="rounded-md border border-line px-3 py-1.5 text-xs text-slate-300 transition hover:border-accent"
      >
        🧩 {translate(lang, "marketplace")}
      </button>

      <div className="mx-2 h-6 w-px bg-line" />

      {(
        [
          ["ai", "🤖", "dockAI"],
          ["agent", "✦", "dockAgent"],
          ["data", "🗄", "dockData"],
          ["simulation", "⚛", "dockSimulation"],
        ] as const
      ).map(([tab, icon, key]) => (
        <button
          key={tab}
          type="button"
          onClick={() => setDockTab(tab)}
          title={translate(lang, key)}
          className="rounded-md border border-line px-2 py-1.5 text-xs text-slate-300 transition hover:border-accent"
        >
          {icon}
        </button>
      ))}

      <div className="mx-2 h-6 w-px bg-line" />

      <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
        {translate(lang, "demos")}
        <select
          defaultValue=""
          onChange={(event) => {
            const file = event.target.value;
            if (!file) return;
            api
              .workflow(file)
              .then((payload) => {
                loadWorkflow(payload as { nodes?: unknown[]; edges?: unknown[] });
                pushLog(`$ loaded ${file}`);
                event.target.value = "";
              })
              .catch((error) => pushLog(`! ${(error as Error).message}`));
          }}
          className="rounded-md border border-line bg-canvas px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-accent"
        >
          <option value="">—</option>
          {demos.map((demo) => (
            <option key={demo.file} value={demo.file}>
              {demo.name}
            </option>
          ))}
        </select>
      </label>

      <div className="flex-1" />

      <span
        className={`rounded px-2 py-0.5 text-[10px] ${
          backend === "online"
            ? "bg-good/15 text-good"
            : backend === "offline"
              ? "bg-bad/15 text-bad"
              : "bg-line text-slate-400"
        }`}
      >
        {backend === "online"
          ? translate(lang, "ready")
          : backend === "offline"
            ? translate(lang, "offline")
            : translate(lang, "connecting")}
      </span>

      <span className="text-[10px] text-slate-500">
        {nodes.length} {translate(lang, "nodes")} · {edges.length}{" "}
        {translate(lang, "edges")}
      </span>

      <button
        type="button"
        onClick={toggleLang}
        className="rounded-md border border-line px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:border-accent"
      >
        {lang === "zh" ? "中 / EN" : "EN / 中"}
      </button>
    </header>
  );
}
