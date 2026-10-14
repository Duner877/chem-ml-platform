/** Simulation panel: pick a family / back-end, submit a job, watch the queue. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { SimulationBackend, SimulationJob } from "../types";

const FAMILIES = [
  { value: "quantum", label: "量子化学 Quantum" },
  { value: "md", label: "分子动力学 MD" },
  { value: "materials", label: "材料 Materials" },
];

export default function SimulationPanel() {
  const { lang, pushLog } = useEditor();
  const [backends, setBackends] = useState<SimulationBackend[]>([]);
  const [jobs, setJobs] = useState<SimulationJob[]>([]);
  const [family, setFamily] = useState("quantum");
  const [backend, setBackend] = useState("");
  const [smiles, setSmiles] = useState("CCO");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [external, history] = await Promise.all([api.simBackends(), api.simJobs()]);
      setBackends(external.backends);
      setJobs(history.jobs);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function run() {
    if (!smiles.trim()) return;
    setBusy(true);
    setError("");
    try {
      const job = await api.simRun({
        family,
        backend,
        smiles: smiles.trim(),
        force_internal: false,
      });
      pushLog(`$ simulation ${family} -> ${job.status} (${job.engine})`);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
      pushLog(`! ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const familyBackends = backends.filter((item) => item.family === family);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-slate-200">{translate(lang, "simPanel")}</h2>
        <p className="mt-0.5 text-[10px] text-slate-500">
          {translate(lang, "simAvailable")}:{" "}
          {backends.filter((item) => item.available).map((item) => item.name).join(", ") || "—"}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {error && <p className="mb-2 text-[11px] text-bad">{error}</p>}

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "simRun")}
          </h3>
          <label className="mb-2 block">
            <span className="mb-1 block text-[10px] text-slate-500">
              {translate(lang, "simFamily")}
            </span>
            <select
              value={family}
              onChange={(event) => {
                setFamily(event.target.value);
                setBackend("");
              }}
              className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-slate-200 outline-none focus:border-accent"
            >
              {FAMILIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mb-2 block">
            <span className="mb-1 block text-[10px] text-slate-500">
              {translate(lang, "simBackend")}
            </span>
            <select
              value={backend}
              onChange={(event) => setBackend(event.target.value)}
              className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-slate-200 outline-none focus:border-accent"
            >
              <option value="">auto</option>
              {familyBackends.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                  {item.is_external ? (item.available ? " ✓" : " (missing)") : " (built-in)"}
                </option>
              ))}
            </select>
          </label>
          <input
            value={smiles}
            onChange={(event) => setSmiles(event.target.value)}
            placeholder={translate(lang, "simSmiles")}
            className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 font-mono text-[11px] text-slate-200 outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={run}
            disabled={busy}
            className="mt-2 rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-canvas hover:bg-accent/85 disabled:opacity-40"
          >
            {busy ? translate(lang, "simRunning") : translate(lang, "simRun")}
          </button>
        </section>

        <section>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "simJobs")} ({jobs.length})
          </h3>
          {jobs.length === 0 ? (
            <p className="text-[11px] text-slate-500">{translate(lang, "simEmpty")}</p>
          ) : (
            <ul className="space-y-1.5">
              {jobs.map((job) => (
                <li key={job.id} className="rounded-md border border-line bg-canvas px-2 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-medium text-slate-200">{job.family}</span>
                    <span className="rounded bg-line px-1 text-[9px] text-slate-400">
                      {job.backend || "auto"}
                    </span>
                    <span
                      className={`ml-auto text-[9px] ${
                        job.status === "completed"
                          ? "text-good"
                          : job.status === "failed"
                            ? "text-bad"
                            : "text-accent"
                      }`}
                    >
                      {job.status}
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-[9px] text-slate-500">
                    {job.engine || "—"} · {job.duration_ms.toFixed(0)} ms
                    {job.error ? ` · ${job.error}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
