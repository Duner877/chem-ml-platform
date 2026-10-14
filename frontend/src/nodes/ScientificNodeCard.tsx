/** Custom React Flow node rendering a scientific node. */

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import type { NodeStatus } from "../store";
import type { NodeSpec } from "../types";

const STATUS_STYLE: Record<NodeStatus, { dot: string; border: string }> = {
  idle: { dot: "bg-slate-500", border: "border-line" },
  running: { dot: "bg-warn animate-pulse", border: "border-warn" },
  completed: { dot: "bg-good", border: "border-good" },
  failed: { dot: "bg-bad", border: "border-bad" },
  skipped: { dot: "bg-slate-600", border: "border-slate-600" },
};

interface NodeData {
  type: string;
  label: string;
  spec: NodeSpec;
  params: Record<string, unknown>;
  status?: NodeStatus;
  logs?: string[];
}

function ScientificNodeCard({ data, selected }: NodeProps) {
  const nodeData = data as unknown as NodeData;
  const spec = nodeData.spec;
  const status: NodeStatus = nodeData.status ?? "idle";
  const style = STATUS_STYLE[status];

  return (
    <div
      className={`w-[220px] rounded-lg border ${style.border} ${
        selected ? "ring-2 ring-accent" : ""
      } bg-panel shadow-lg shadow-black/40`}
    >
      {/* header -------------------------------------------------------- */}
      <div className="flex items-center gap-2 rounded-t-lg border-b border-line bg-panel2 px-3 py-2">
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${style.dot}`}
          aria-label={status}
        />
        <span className="truncate text-sm font-medium text-slate-100">
          {nodeData.label ?? spec?.name}
        </span>
      </div>

      {/* body ---------------------------------------------------------- */}
      <div className="px-3 py-2">
        <div className="mb-1 text-[10px] uppercase tracking-wide text-accent/80">
          {spec?.category}
        </div>
        <div className="line-clamp-2 text-xs text-slate-400">
          {spec?.description}
        </div>
      </div>

      {/* ports --------------------------------------------------------- */}
      <div className="relative flex justify-between px-3 pb-3 pt-1">
        <div className="flex flex-col gap-1">
          {(spec?.inputs ?? []).slice(0, 4).map((port) => (
            <div
              key={port.name}
              className="relative flex items-center gap-1 text-[10px] text-slate-400"
            >
              <Handle
                type="target"
                position={Position.Left}
                id={port.name}
                className="!static !h-2 !w-2 !min-w-0 !translate-x-[-10px]"
                style={{ background: port.optional ? "#64748b" : "#38bdf8" }}
              />
              <span className="truncate">{port.name}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-col items-end gap-1">
          {(spec?.outputs ?? []).slice(0, 4).map((port) => (
            <div
              key={port.name}
              className="relative flex items-center gap-1 text-[10px] text-slate-400"
            >
              <span className="truncate">{port.name}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port.name}
                className="!static !h-2 !w-2 !min-w-0 !translate-x-[10px]"
                style={{ background: "#34d399" }}
              />
            </div>
          ))}
        </div>
      </div>    </div>
  );
}

export default memo(ScientificNodeCard);
