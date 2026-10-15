/** Bottom run bar — the ComfyUI-style status strip.
 *
 * Left: a translucent status overlay (version, backend, node/edge counts, last
 * run). Centre: the Run button with a queue badge and the validate action.
 * Right: canvas zoom / fit / lock controls.
 */

import { useReactFlow } from "@xyflow/react";
import { useEffect } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { useRunActions } from "../workflowActions";
import {
  IconCheck,
  IconExpand,
  IconLock,
  IconMinus,
  IconPlay,
  IconPlus,
  IconUnlock,
} from "./Icons";

export default function BottomBar() {
  const {
    lang,
    nodes,
    edges,
    busy,
    backend,
    runResult,
    status,
    canvasLocked,
    setCanvasLocked,
  } = useEditor();
  const { handleRun, handleValidate } = useRunActions();
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  // The Edit → Zoom to fit menu item reaches into React Flow through this
  // document event, keeping TopBar free of flow-context dependencies.
  useEffect(() => {
    function onZoomFit() {
      fitView({ padding: 0.2, duration: 300 });
    }
    window.addEventListener("chemml:zoom-fit", onZoomFit);
    return () => window.removeEventListener("chemml:zoom-fit", onZoomFit);
  }, [fitView]);

  const statusText =
    status === "running"
      ? translate(lang, "running")
      : status === "completed"
        ? translate(lang, "completed")
        : status === "failed"
          ? translate(lang, "failed")
          : translate(lang, "idle");

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex items-end justify-between p-3">
      {/* status overlay --------------------------------------------------- */}
      <div className="cml-menu pointer-events-auto flex items-center gap-3 px-3 py-1.5 text-[10px] text-[rgb(var(--c-text-dim))]">
        <span className="font-mono text-[rgb(var(--c-text))]">v{__CHEMML_VERSION__}</span>
        <span className="h-3 w-px bg-line" />
        <span className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              backend === "online"
                ? "bg-good"
                : backend === "offline"
                  ? "bg-bad"
                  : "bg-[rgb(var(--c-text-faint))]"
            }`}
          />
          {translate(lang, "backendState")}{" "}
          {backend === "online"
            ? translate(lang, "ready")
            : backend === "offline"
              ? translate(lang, "offline")
              : translate(lang, "connecting")}
        </span>
        <span className="h-3 w-px bg-line" />
        <span>
          {nodes.length} {translate(lang, "nodes")} · {edges.length}{" "}
          {translate(lang, "edges")}
        </span>
        {runResult && (
          <>
            <span className="h-3 w-px bg-line" />
            <span>
              {translate(lang, "lastRun")} {runResult.duration_ms.toFixed(0)} ms
            </span>
          </>
        )}
        <span className="h-3 w-px bg-line" />
        <span className={status === "failed" ? "text-bad" : undefined}>{statusText}</span>
      </div>

      {/* run controls ----------------------------------------------------- */}
      <div className="pointer-events-auto flex items-center gap-2">
        <button
          type="button"
          onClick={() => void handleValidate()}
          disabled={nodes.length === 0}
          title={translate(lang, "validate")}
          className="cml-menu flex h-9 items-center gap-1.5 px-3 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:text-[rgb(var(--c-text))] disabled:opacity-40"
        >
          <IconCheck size={14} />
          <span className="hidden sm:inline">{translate(lang, "validate")}</span>
        </button>

        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={busy || nodes.length === 0}
          className="flex h-9 items-center gap-2 rounded-md bg-accent px-4 text-xs font-semibold text-onAccent shadow-lg shadow-black/30 transition hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <IconPlay size={13} />
          {busy ? `${translate(lang, "running")}…` : translate(lang, "run")}
        </button>

        <span
          title={translate(lang, "queue")}
          className="cml-menu flex h-9 min-w-9 items-center justify-center px-2 font-mono text-[11px] text-[rgb(var(--c-text))]"
        >
          {busy ? 1 : 0}
        </span>
      </div>

      {/* canvas controls ---------------------------------------------------- */}
      <div className="pointer-events-auto cml-menu flex flex-col overflow-hidden">
        <button
          type="button"
          title={translate(lang, "zoomIn")}
          onClick={() => zoomIn({ duration: 200 })}
          className="flex h-8 w-8 items-center justify-center text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          <IconPlus size={14} />
        </button>
        <button
          type="button"
          title={translate(lang, "zoomOut")}
          onClick={() => zoomOut({ duration: 200 })}
          className="flex h-8 w-8 items-center justify-center border-y border-line text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          <IconMinus size={14} />
        </button>
        <button
          type="button"
          title={translate(lang, "zoomToFit")}
          onClick={() => fitView({ padding: 0.2, duration: 300 })}
          className="flex h-8 w-8 items-center justify-center text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          <IconExpand size={14} />
        </button>
        <button
          type="button"
          title={canvasLocked ? translate(lang, "unlockCanvas") : translate(lang, "lockCanvas")}
          onClick={() => setCanvasLocked(!canvasLocked)}
          className={`flex h-8 w-8 items-center justify-center border-t border-line transition hover:bg-panel2 ${
            canvasLocked
              ? "text-accent"
              : "text-[rgb(var(--c-text-dim))] hover:text-[rgb(var(--c-text))]"
          }`}
        >
          {canvasLocked ? <IconLock size={14} /> : <IconUnlock size={14} />}
        </button>
      </div>
    </div>
  );
}
