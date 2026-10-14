/** Right panel: parameter inspector for the selected node. */

import { useEditor } from "../store";
import { translate } from "../i18n";
import type { NodeParamSpec } from "../types";

function ParamField({
  spec,
  value,
  onChange,
}: {
  spec: NodeParamSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const base =
    "w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-accent";

  const enumOptions = (spec.options ?? []).map((option) =>
    Array.isArray(option) ? { value: String(option[0]), label: String(option[1] ?? option[0]) } : { value: String(option), label: String(option) }
  );

  if (spec.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-3.5 w-3.5 accent-accent"
        />
        {spec.description || spec.name}
      </label>
    );
  }

  if (spec.type === "enum") {
    return (
      <select
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        className={base}
      >
        {enumOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (spec.type === "text") {
    return (
      <textarea
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        rows={5}
        className={`${base} font-mono`}
      />
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
        className={base}
      />
    );
  }

  if (spec.type === "file") {
    return (
      <input
        type="text"
        value={String(value ?? "")}
        placeholder="path/to/file"
        onChange={(event) => onChange(event.target.value)}
        className={`${base} font-mono`}
      />
    );
  }

  return (
    <input
      type="text"
      value={String(value ?? "")}
      onChange={(event) => onChange(event.target.value)}
      className={base}
    />
  );
}

export default function Inspector() {
  const { nodes, selectedId, updateParams, updateLabel, duplicateNode, removeNode, lang } =
    useEditor();

  const node = nodes.find((item) => item.id === selectedId);

  if (!node) {
    return (
      <div className="flex h-full flex-col">
        <header className="border-b border-line px-3 py-3">
          <h2 className="text-sm font-semibold text-slate-200">
            {translate(lang, "inspector")}
          </h2>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-3xl">🧪</div>
          <p className="text-xs text-slate-500">{translate(lang, "selectHint")}</p>
        </div>
      </div>
    );
  }

  const data = node.data as unknown as {
    type: string;
    label: string;
    spec: import("../types").NodeSpec;
    params: Record<string, unknown>;
    status?: string;
    logs?: string[];
  };

  const basic = data.spec.parameters.filter((spec) => !spec.advanced);
  const advanced = data.spec.parameters.filter((spec) => spec.advanced);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">
            {translate(lang, "inspector")}
          </h2>
          <span className="rounded bg-line px-1.5 py-0.5 text-[10px] text-slate-300">
            {data.type}
          </span>
        </div>
        <input
          value={data.label}
          onChange={(event) => updateLabel(node.id, event.target.value)}
          className="mt-2 w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-xs text-slate-100 outline-none focus:border-accent"
        />
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => duplicateNode(node.id)}
            className="rounded border border-line px-2 py-1 text-[11px] text-slate-300 hover:border-accent"
          >
            {translate(lang, "duplicate")}
          </button>
          <button
            type="button"
            onClick={() => removeNode(node.id)}
            className="rounded border border-line px-2 py-1 text-[11px] text-bad hover:border-bad"
          >
            {translate(lang, "delete")}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <section className="mb-4">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "inputs")} ({data.spec.inputs.length})
          </h3>
          <ul className="space-y-0.5">
            {data.spec.inputs.map((port) => (
              <li key={port.name} className="flex items-center gap-2 text-[11px]">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    port.optional ? "bg-slate-500" : "bg-accent"
                  }`}
                />
                <span className="font-mono text-slate-200">{port.name}</span>
                <span className="text-slate-500">{port.data_type}</span>
                {port.multi && (
                  <span className="rounded bg-line px-1 text-[9px] text-slate-400">
                    {translate(lang, "multi")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-4">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "outputs")} ({data.spec.outputs.length})
          </h3>
          <ul className="space-y-0.5">
            {data.spec.outputs.map((port) => (
              <li key={port.name} className="flex items-center gap-2 text-[11px]">
                <span className="h-1.5 w-1.5 rounded-full bg-good" />
                <span className="font-mono text-slate-200">{port.name}</span>
                <span className="text-slate-500">{port.data_type}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "parameters")}
          </h3>
          <div className="space-y-3">
            {basic.map((spec) => (
              <label key={spec.name} className="block">
                <div className="mb-1 flex items-center gap-2">
                  <span className="font-mono text-[11px] text-slate-200">
                    {spec.name}
                  </span>
                  {spec.unit && (
                    <span className="text-[9px] text-slate-500">({spec.unit})</span>
                  )}
                </div>
                {spec.description && (
                  <p className="mb-1 text-[10px] text-slate-500">{spec.description}</p>
                )}
                <ParamField
                  spec={spec}
                  value={data.params[spec.name]}
                  onChange={(value) =>
                    updateParams(node.id, { ...data.params, [spec.name]: value })
                  }
                />
              </label>
            ))}
            {basic.length === 0 && (
              <p className="text-[11px] text-slate-500">—</p>
            )}
          </div>
        </section>

        {advanced.length > 0 && (
          <section className="mb-4">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Advanced
            </h3>
            <div className="space-y-3">
              {advanced.map((spec) => (
                <label key={spec.name} className="block">
                  <span className="mb-1 block font-mono text-[11px] text-slate-300">
                    {spec.name}
                  </span>
                  <ParamField
                    spec={spec}
                    value={data.params[spec.name]}
                    onChange={(value) =>
                      updateParams(node.id, { ...data.params, [spec.name]: value })
                    }
                  />
                </label>
              ))}
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "description")}
          </h3>
          <p className="text-[11px] leading-relaxed text-slate-400">
            {data.spec.description || "—"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {data.spec.tags.map((tag) => (
              <span
                key={tag}
                className="rounded bg-line px-1.5 py-0.5 text-[9px] text-slate-300"
              >
                {tag}
              </span>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
