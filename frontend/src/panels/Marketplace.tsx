/** Node Marketplace: browse the full node registry and drag / add nodes. */

import { useEffect, useMemo, useState } from "react";
import { useEditor } from "../store";
import { api } from "../api";
import { translate } from "../i18n";
import type { RegistryNode, RegistryPayload } from "../types";

export default function Marketplace() {
  const { specs, addNode, setMarketplace, lang } = useEditor();
  const [registry, setRegistry] = useState<RegistryPayload | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .registry()
      .then((payload) => {
        if (!cancelled) setRegistry(payload);
      })
      .catch(() => setRegistry(null));
    return () => {
      cancelled = true;
    };
  }, []);

  const displayName = (node: RegistryNode) =>
    lang === "zh" ? node.name_zh || node.node_name : node.node_name;
  const displayCategory = (node: RegistryNode) =>
    lang === "zh" ? node.category_zh || node.category : node.category;
  const displayDescription = (node: RegistryNode) =>
    lang === "zh" ? node.description : node.description_en || node.description;

  const filtered = useMemo<RegistryNode[]>(() => {
    if (!registry) return [];
    const needle = query.trim().toLowerCase();
    return registry.nodes
      .filter((node) => !category || node.category === category)
      .filter((node) => {
        if (!needle) return true;
        return (
          node.node_name.toLowerCase().includes(needle) ||
          (node.name_zh ?? "").toLowerCase().includes(needle) ||
          node.type.toLowerCase().includes(needle) ||
          node.description.toLowerCase().includes(needle) ||
          (node.description_en ?? "").toLowerCase().includes(needle) ||
          node.tags.some((tag) => tag.toLowerCase().includes(needle)) ||
          node.author.toLowerCase().includes(needle)
        );
      })
      .sort(
        (a, b) =>
          a.category.localeCompare(b.category) || a.node_name.localeCompare(b.node_name)
      );
  }, [registry, query, category]);

  const categories = useMemo(() => {
    const names = new Set<string>();
    for (const node of registry?.nodes ?? []) names.add(node.category);
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [registry]);

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-canvas/95 backdrop-blur-sm">
      <header className="flex items-center gap-3 border-b border-line bg-panel px-4 py-3">
        <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
          {translate(lang, "marketplace")}
        </h2>
        <span className="text-[11px] text-[rgb(var(--c-text-faint))]">
          {registry ? `${registry.total_nodes} ${translate(lang, "nodes")}` : "…"}
          {registry?.valid ? " · valid" : ""}
        </span>

        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={translate(lang, "search")}
          className="cml-widget ml-2 w-64"
        />

        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          className="cml-widget w-48"
        >
          <option value="">{translate(lang, "allCategories")}</option>
          {categories.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>

        <div className="flex-1" />

        <button
          type="button"
          onClick={() => setMarketplace(false)}
          className="rounded-md border border-line px-3 py-1.5 text-xs text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          ✕ {translate(lang, "close")}
        </button>
      </header>

      <div className="grid flex-1 auto-rows-min grid-cols-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.length === 0 && (
          <p className="col-span-full px-2 py-8 text-center text-xs text-[rgb(var(--c-text-faint))]">
            {translate(lang, "emptyMarketplace")}
          </p>
        )}
        {filtered.map((node) => {
          const installed = Boolean(specs[node.type]);
          return (
            <article
              key={node.type}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData("application/chemml-node", node.type);
                event.dataTransfer.effectAllowed = "move";
              }}
              className="flex flex-col rounded-lg border border-line bg-panel p-3 transition hover:border-accent"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-xs font-semibold text-[rgb(var(--c-text))]">
                  {displayName(node)}
                </h3>
                <span className="shrink-0 rounded bg-panel2 px-1.5 text-[9px] text-[rgb(var(--c-text-dim))]">
                  v{node.version}
                </span>
              </div>

              <div className="mt-1 flex flex-wrap gap-1 text-[9px]">
                <span className="rounded bg-accent/15 px-1.5 py-0.5 text-accent">
                  {displayCategory(node)}
                </span>
                {node.tags.slice(0, 3).map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-panel2 px-1.5 py-0.5 text-[rgb(var(--c-text-dim))]"
                  >
                    {tag}
                  </span>
                ))}
              </div>

              <p className="mt-2 line-clamp-3 flex-1 text-[11px] leading-relaxed text-[rgb(var(--c-text-dim))]">
                {displayDescription(node)}
              </p>

              <div className="mt-2 flex items-center justify-between text-[9px] text-[rgb(var(--c-text-faint))]">
                <span>
                  {node.inputs.length} {translate(lang, "nodeIn")} · {node.outputs.length}{" "}
                  {translate(lang, "nodeOut")}
                </span>
                <span>
                  {installed ? translate(lang, "installed") : translate(lang, "notInstalled")}
                </span>
              </div>

              <button
                type="button"
                disabled={!installed}
                onClick={() => addNode(node.type)}
                className="mt-2 rounded-md bg-accent px-2 py-1 text-[11px] font-semibold text-onAccent transition hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
              >
                + {translate(lang, "addNode")}
              </button>
            </article>
          );
        })}
      </div>
    </div>
  );
}
