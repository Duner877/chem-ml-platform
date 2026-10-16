/** ComfyUI-style node card for the scientific workflow canvas.
 *
 * Visual language of the reference editor: a rounded card with a coloured
 * header accent, inline *widgets* (parameters editable directly on the node),
 * type-coloured ports on both edges and a compact description strip.  All text
 * follows the active language; all colours follow the active theme.
 */

import { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { useEditor, useThemeTokens, type NodeStatus } from "../store";
import { portColor } from "../theme";
import FilePickerField from "../components/FilePickerField";
import type { NodeParamSpec, NodeSpec } from "../types";

const STATUS_STYLE: Record<NodeStatus, { dot: string; border: string; ring: string }> = {
  idle: { dot: "bg-[rgb(var(--c-text-faint))]", border: "border-nodeBorder", ring: "" },
  running: {
    dot: "bg-warn animate-pulse",
    border: "border-warn",
    ring: "ring-1 ring-warn/60",
  },
  completed: { dot: "bg-good", border: "border-good", ring: "ring-1 ring-good/60" },
  failed: { dot: "bg-bad", border: "border-bad", ring: "ring-1 ring-bad/60" },
  skipped: {
    dot: "bg-[rgb(var(--c-text-faint))]",
    border: "border-nodeBorder",
    ring: "",
  },
};

/**
 * Category accents (header dot + category chip).
 *
 * v0.7.2: these used to be One Dark accents (cyan / purple / orange / ...).
 * Under the monochrome WorkBuddy language they became greyscale steps keyed by
 * the *position* of the category in this table, so the chip still separates
 * categories from each other without reintroducing a rainbow.
 *
 * The steps come from the **active theme's** greyscale ramp, so the dot stays
 * visible: near-black on the white theme, near-white on the black one.
 */
const CATEGORY_ACCENTS: Array<[string, number]> = [
  ["Instruments", 0],
  ["Databases", 2],
  ["Simulation", 4],
  ["AI", 5],
  ["Agent", 1],
  ["Report", 4],
  ["Questions", 1],
  ["Analysis", 3],
  ["IO", 6],
  ["GPU", 2],
];

/** Greyscale ramp per theme: light runs dark→light, dark runs light→dark. */
const CATEGORY_RAMP: Record<string, readonly string[]> = {
  "wb-light": [
    "26 30 40",
    "58 65 77",
    "90 98 111",
    "122 131 144",
    "154 163 175",
    "186 194 205",
    "212 218 226",
  ],
  "wb-dark": [
    "240 242 246",
    "206 211 220",
    "172 179 190",
    "138 146 159",
    "104 112 125",
    "72 79 90",
    "44 49 58",
  ],
};

/** Accent for ``category`` under ``theme`` (falls back to a neutral step). */
function categoryAccent(category: string, theme: string): string {
  const ramp = CATEGORY_RAMP[theme] ?? CATEGORY_RAMP["wb-dark"];
  for (const [prefix, step] of CATEGORY_ACCENTS) {
    if (category.startsWith(prefix)) return ramp[step] ?? ramp[3];
  }
  return ramp[3];
}

interface NodeData {
  type: string;
  label: string;
  label_en: string;
  spec: NodeSpec;
  params: Record<string, unknown>;
  status?: NodeStatus;
  logs?: string[];
}

/** Compact inline widget — mirrors the inspector control, node-sized. */
function Widget({
  spec,
  value,
  onChange,
}: {
  spec: NodeParamSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { lang } = useEditor();

  if (spec.type === "boolean") {
    return (
      <label className="flex items-center gap-1.5 text-[10px] text-[rgb(var(--c-text-dim))]">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-3 w-3 accent-[rgb(var(--c-accent))]"
        />
        {spec.description || spec.name}
      </label>
    );
  }

  if (spec.type === "enum") {
    const source =
      lang === "en" && spec.options_en?.length ? spec.options_en : spec.options;
    const options = (source ?? []).map((option) =>
      Array.isArray(option)
        ? { value: String(option[0]), label: String(option[1] ?? option[0]) }
        : { value: String(option), label: String(option) }
    );
    return (
      <select
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        className="cml-widget"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (spec.type === "number" || spec.type === "integer") {
    return (
      <input
        type="number"
        value={value === null || value === undefined ? "" : Number(value)}
        min={spec.min ?? undefined}
        max={spec.max ?? undefined}
        step={spec.step ?? undefined}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") return onChange(null);
          const parsed = spec.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(parsed) ? null : parsed);
        }}
        className="cml-widget"
      />
    );
  }

  if (spec.type === "text") {
    return (
      <textarea
        value={String(value ?? "")}
        rows={3}
        onChange={(event) => onChange(event.target.value)}
        className="cml-widget resize-none"
      />
    );
  }

  // v0.7.2: a file parameter is a path the user should not have to type.
  if (spec.type === "file") {
    return (
      <FilePickerField
        compact
        value={value}
        description={spec.description_en || spec.description || spec.name}
        onChange={onChange}
      />
    );
  }

  return (
    <input
      type="text"
      value={String(value ?? "")}
      placeholder={spec.name}
      onChange={(event) => onChange(event.target.value)}
      className="cml-widget"
    />
  );
}

function ScientificNodeCard({ data, selected, id }: NodeProps) {
  const nodeData = data as unknown as NodeData;
  const spec = nodeData.spec;
  const status: NodeStatus = nodeData.status ?? "idle";
  const style = STATUS_STYLE[status];
  const tokens = useThemeTokens();
  const { lang, theme, updateParams } = useEditor();

  const onParamChange = useCallback(
    (name: string, value: unknown) => {
      updateParams(id, { ...nodeData.params, [name]: value });
    },
    [id, nodeData.params, updateParams]
  );

  const inputs = spec?.inputs ?? [];
  const outputs = spec?.outputs ?? [];
  const widgets = (spec?.parameters ?? []).filter((param) => !param.advanced).slice(0, 4);
  const hiddenWidgets = (spec?.parameters ?? []).filter((param) => !param.advanced).length - widgets.length;
  const accent = categoryAccent(spec?.category ?? "", theme);

  const title = lang === "zh" ? nodeData.label ?? spec?.name : nodeData.label_en ?? spec?.name;
  const description =
    lang === "zh" ? spec?.description : spec?.description_en || spec?.description;
  const categoryLabel =
    lang === "zh" ? spec?.category_zh || spec?.category : spec?.category;

  return (
    <div
      className={`w-[240px] rounded-lg border ${style.border} ${
        selected ? `ring-2 ring-accent ${style.ring}` : style.ring
      } bg-nodeBody shadow-xl shadow-black/40`}
    >
      {/* header ---------------------------------------------------------- */}
      <div className="flex items-center gap-2 rounded-t-lg border-b border-nodeBorder bg-nodeHeader px-2.5 py-1.5">
        <span
          className="h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ background: accent }}
        />
        <span className="truncate text-[11px] font-semibold text-[rgb(var(--c-text))]">
          {title}
        </span>
        <span className={`ml-auto h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
      </div>

      {/* description strip ------------------------------------------------- */}
      {description && (
        <p className="line-clamp-2 px-2.5 pt-1.5 text-[9px] leading-relaxed text-[rgb(var(--c-text-faint))]">
          {description}
        </p>
      )}

      {/* widgets ---------------------------------------------------------- */}
      {widgets.length > 0 && (
        <div className="space-y-1.5 px-2.5 py-2">
          {widgets.map((param) => (
            <div key={param.name}>
              <div className="mb-0.5 flex items-center gap-1.5">
                <span className="font-mono text-[9px] text-[rgb(var(--c-text-dim))]">
                  {param.name}
                </span>
                {param.unit && (
                  <span className="text-[8px] text-[rgb(var(--c-text-faint))]">
                    ({param.unit})
                  </span>
                )}
              </div>
              <Widget
                spec={param}
                value={nodeData.params?.[param.name]}
                onChange={(value) => onParamChange(param.name, value)}
              />
            </div>
          ))}
          {hiddenWidgets > 0 && (
            <p className="text-[8px] text-[rgb(var(--c-text-faint))]">
              +{hiddenWidgets} {lang === "zh" ? "个参数见检查器" : "more in the inspector"}
            </p>
          )}
        </div>
      )}

      {/* category + ports --------------------------------------------------- */}
      <div className="flex items-center gap-2 px-2.5 pb-1 pt-0.5">
        <span className="rounded px-1.5 py-0.5 text-[8px]" style={{ background: `${accent}22`, color: accent }}>
          {categoryLabel}
        </span>
        <span className="text-[8px] text-[rgb(var(--c-text-faint))]">
          {inputs.length} {lang === "zh" ? "入" : "in"} · {outputs.length}{" "}
          {lang === "zh" ? "出" : "out"}
        </span>
      </div>

      <div className="relative flex justify-between gap-4 px-2.5 pb-2.5">
        {/* inputs ---------------------------------------------------------- */}
        <div className="flex flex-col gap-1">
          {inputs.slice(0, 4).map((port) => (
            <div
              key={port.name}
              className="relative flex items-center gap-1.5 text-[9px] text-[rgb(var(--c-text-dim))]"
            >
              <Handle
                type="target"
                position={Position.Left}
                id={port.name}
                className="!static !h-2.5 !w-2.5 !min-w-0 !translate-x-[-14px] !rounded-full"
                style={{
                  background: `rgb(${portColor(tokens, port.data_type)})`,
                  border: "2px solid rgb(var(--c-node-body))",
                }}
              />
              <span className="truncate">{port.name}</span>
              {/* v0.7.2: this used to be a bare "?".  A question mark reads
                  as "something is missing/broken", which is the opposite of
                  what an optional port means.  It is now an explicit
                  "可选 / opt" chip (full wording in the inspector). */}
              {port.optional && (
                <span
                  title={lang === "zh" ? "可选输入端口" : "optional input port"}
                  className="shrink-0 rounded-sm border border-line px-1 text-[7px] leading-[9px] text-[rgb(var(--c-text-faint))]"
                >
                  {lang === "zh" ? "可选" : "opt"}
                </span>
              )}
            </div>
          ))}
          {inputs.length > 4 && (
            <span className="text-[8px] text-[rgb(var(--c-text-faint))]">
              +{inputs.length - 4}
            </span>
          )}
        </div>

        {/* outputs --------------------------------------------------------- */}
        <div className="flex flex-col items-end gap-1">
          {outputs.slice(0, 4).map((port) => (
            <div
              key={port.name}
              className="relative flex items-center gap-1.5 text-[9px] text-[rgb(var(--c-text-dim))]"
            >
              <span className="truncate">{port.name}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port.name}
                className="!static !h-2.5 !w-2.5 !min-w-0 !translate-x-[14px] !rounded-full"
                style={{
                  background: `rgb(${portColor(tokens, port.data_type)})`,
                  border: "2px solid rgb(var(--c-node-body))",
                }}
              />
            </div>
          ))}
          {outputs.length > 4 && (
            <span className="text-[8px] text-[rgb(var(--c-text-faint))]">
              +{outputs.length - 4}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(ScientificNodeCard);
