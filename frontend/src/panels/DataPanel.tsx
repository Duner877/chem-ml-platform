/** Scientific data panel: ingest datasets into the catalog and browse entries. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { CatalogEntry, CatalogStats } from "../types";

export default function DataPanel() {
  const { lang, pushLog } = useEditor();
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [stats, setStats] = useState<CatalogStats | null>(null);
  const [datasets, setDatasets] = useState<Array<{ path: string; name: string }>>([]);
  const [query, setQuery] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async (search = "") => {
    try {
      const result = await api.dataCatalog(search);
      setEntries(result.entries);
      setStats(result.stats);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
    api
      .datasets()
      .then((list) => setDatasets(list.slice(0, 60)))
      .catch(() => setDatasets([]));
  }, [refresh]);

  async function ingest() {
    const target = path.trim();
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.dataIngest(target, ["ui"]);
      pushLog(`$ data.ingest ${target} -> ${result.count} object(s)`);
      setPath("");
      await refresh(query);
    } catch (err) {
      setError((err as Error).message);
      pushLog(`! ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">{translate(lang, "dataPanel")}</h2>
        {stats && (
          <p className="mt-0.5 text-[10px] text-[rgb(var(--c-text-faint))]">
            {stats.count} {translate(lang, "dataEntries")} · {stats.embedded}{" "}
            {translate(lang, "dataEmbedded")}
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {error && <p className="mb-2 text-[11px] text-bad">{error}</p>}

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "dataIngest")}
          </h3>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder={translate(lang, "dataPath")}
            className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 font-mono text-[11px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
          />
          {datasets.length > 0 && (
            <select
              onChange={(event) => setPath(event.target.value)}
              defaultValue=""
              className="mt-1.5 w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-[rgb(var(--c-text-dim))] outline-none focus:border-accent"
            >
              <option value="">{translate(lang, "dataSamples")}…</option>
              {datasets.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.path}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={ingest}
            disabled={busy}
            className="mt-2 rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-canvas hover:bg-accent/85 disabled:opacity-40"
          >
            {busy ? translate(lang, "dataIngesting") : translate(lang, "dataIngest")}
          </button>
        </section>

        <section>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "dataCatalog")}
          </h3>
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              refresh(event.target.value);
            }}
            placeholder={translate(lang, "dataSearchHint")}
            className="mb-2 w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
          />
          {entries.length === 0 ? (
            <p className="text-[11px] text-[rgb(var(--c-text-faint))]">{translate(lang, "dataEmpty")}</p>
          ) : (
            <ul className="space-y-1.5">
              {entries.map((entry) => (
                <li
                  key={entry.id}
                  className="rounded-md border border-line bg-canvas px-2 py-1.5"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-medium text-[rgb(var(--c-text))]">
                      {entry.sample || entry.type}
                    </span>
                    <span className="rounded bg-line px-1 text-[9px] text-[rgb(var(--c-text-faint))]">
                      {entry.type}
                    </span>
                    {entry.embedding_dim ? (
                      <span className="ml-auto font-mono text-[9px] text-good">
                        {entry.embedding_model}·{entry.embedding_dim}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[9px] text-[rgb(var(--c-text-faint))]">
                    {entry.data_pointer || entry.source || "—"}
                  </p>
                  {entry.tags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {entry.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-line px-1 py-0.5 text-[8px] text-[rgb(var(--c-text-faint))]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
