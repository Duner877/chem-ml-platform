/** Right panel: parameter inspector for the selected node. */

import { useEditor } from "../store";
import { translate } from "../i18n";
import type { NodeParamSpec } from "../types";

/** Localized enum option (backend mirrors ``(value, label)`` pairs). */
function enumOptions(spec: NodeParamSpec, lang: "zh" | "en") {
  const source = lang === "en" && spec.options_en?.length ? spec.options_en : spec.options;
  return (source ?? []).map((option) =>
    Array.isArray(option)
      ? { value: String(option[0]), label: String(option[1] ?? option[0]) }
      : { value: String(option), label: String(option) }
  );
}

function ParamField({
  spec,
  value,
  onChange,
}: {
  spec: NodeParamSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { lang } = useEditor();
  const base =
    "cml-widget";

  const label = lang === "en" ? spec.description_en || spec.description : spec.description;

  if (spec.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-xs text-[rgb(var(--c-text-dim))]">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-3.5 w-3.5 accent-[rgb(var(--c-accent))]"
        />
        {label || spec.name}
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
        {enumOptions(spec, lang).map((option) => (
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
        className={`${base} resize-none`}
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
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "inspector")}
          </h2>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-3xl">🧪</div>
          <p className="text-xs text-[rgb(var(--c-text-faint))]">
            {translate(lang, "selectHint")}
          </p>
        </div>
      </div>
    );
  }

  const data = node.data as unknown as {
    type: string;
    label: string;
    label_en: string;
    spec: import("../types").NodeSpec;
    params: Record<string, unknown>;
    status?: string;
    logs?: string[];
  };

  const spec = data.spec;
  const basic = spec.parameters.filter((item) => !item.advanced);
  const advanced = spec.parameters.filter((item) => item.advanced);
  const portDescription = (port: { description: string; description_en?: string }) =>
    lang === "en" ? port.description_en || port.description : port.description;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "inspector")}
          </h2>
          <span className="rounded bg-panel2 px-1.5 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))]">
            {data.type}
          </span>
        </div>

        <label className="mt-2 block text-[10px] text-[rgb(var(--c-text-faint))]">
          {lang === "zh" ? "中文标签" : "Chinese label"}
          <input
            value={data.label}
            onChange={(event) => updateLabel(node.id, event.target.value, "zh")}
            className="cml-widget mt-0.5"
          />
        </label>
        <label className="mt-1.5 block text-[10px] text-[rgb(var(--c-text-faint))]">
          {lang === "zh" ? "英文标签" : "English label"}
          <input
            value={data.label_en ?? ""}
            onChange={(event) => updateLabel(node.id, event.target.value, "en")}
            className="cml-widget mt-0.5"
          />
        </label>

        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => duplicateNode(node.id)}
            className="rounded border border-line px-2 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            {translate(lang, "duplicate")}
          </button>
          <button
            type="button"
            onClick={() => removeNode(node.id)}
            className="rounded border border-line px-2 py-1 text-[11px] text-bad transition hover:border-bad"
          >
            {translate(lang, "delete")}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <section className="mb-4">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">
            {translate(lang, "inputs")} ({spec.inputs.length})
          </h3>
          <ul className="space-y-0.5">
            {spec.inputs.map((port) => (
              <li key={port.name} className="flex items-center gap-2 text-[11px]">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    port.optional ? "bg-[rgb(var(--c-text-faint))]" : "bg-accent"
                  }`}
                />
                <span className="font-mono text-[rgb(var(--c-text))]">{port.name}</span>
                <span className="text-[rgb(var(--c-text-faint))]">{port.data_type}</span>
                <span className="truncate text-[rgb(var(--c-text-faint))]">
                  {portDescription(port)}
                </span>
                {port.multi && (
                  <span className="rounded bg-panel2 px-1 text-[9px] text-[rgb(var(--c-text-dim))]">
                    {translate(lang, "multi")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-4">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">
            {translate(lang, "outputs")} ({spec.outputs.length})
          </h3>
          <ul className="space-y-0.5">
            {spec.outputs.map((port) => (
              <li key={port.name} className="flex items-center gap-2 text-[11px]">
                <span className="h-1.5 w-1.5 rounded-full bg-good" />
                <span className="font-mono text-[rgb(var(--c-text))]">{port.name}</span>
                <span className="text-[rgb(var(--c-text-faint))]">{port.data_type}</span>
                <span className="truncate text-[rgb(var(--c-text-faint))]">
                  {portDescription(port)}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent">
            {translate(lang, "parameters")}
          </h3>
          <div className="space-y-3">
            {basic.map((item) => (
              <label key={item.name} className="block">
                <div className="mb-1 flex items-center gap-2">
                  <span className="font-mono text-[11px] text-[rgb(var(--c-text))]">
                    {item.name}
                  </span>
                  {item.unit && (
                    <span className="text-[9px] text-[rgb(var(--c-text-faint))]">
                      ({item.unit})
                    </span>
                  )}
                </div>
                {(lang === "en" ? item.description_en : item.description) && (
                  <p className="mb-1 text-[10px] text-[rgb(var(--c-text-faint))]">
                    {lang === "en" ? item.description_en : item.description}
                  </p>
                )}
                <ParamField
                  spec={item}
                  value={data.params[item.name]}
                  onChange={(value) =>
                    updateParams(node.id, { ...data.params, [item.name]: value })
                  }
                />
              </label>
            ))}
            {basic.length === 0 && (
              <p className="text-[11px] text-[rgb(var(--c-text-faint))]">—</p>
            )}
          </div>
        </section>

        {advanced.length > 0 && (
          <section className="mb-4">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[rgb(var(--c-text-faint))]">
              Advanced
            </h3>
            <div className="space-y-3">
              {advanced.map((item) => (
                <label key={item.name} className="block">
                  <span className="mb-1 block font-mono text-[11px] text-[rgb(var(--c-text-dim))]">
                    {item.name}
                  </span>
                  <ParamField
                    spec={item}
                    value={data.params[item.name]}
                    onChange={(value) =>
                      updateParams(node.id, { ...data.params, [item.name]: value })
                    }
                  />
                </label>
              ))}
            </div>
          </section>
        )}

        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">
            {translate(lang, "description")}
          </h3>
          <p className="text-[11px] leading-relaxed text-[rgb(var(--c-text-dim))]">
            {lang === "en" ? spec.description_en || spec.description : spec.description}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {spec.tags.map((tag) => (
              <span
                key={tag}
                className="rounded bg-panel2 px-1.5 py-0.5 text-[9px] text-[rgb(var(--c-text-dim))]"
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
