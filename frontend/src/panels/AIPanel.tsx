/** AI runtime panel: mode switch (cloud / local / offline), providers, test prompt. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { AIConfig, AIState, FoundationModel } from "../types";

export default function AIPanel() {
  const { lang, pushLog } = useEditor();
  const [state, setState] = useState<AIState | null>(null);
  const [config, setConfig] = useState<AIConfig | null>(null);
  const [models, setModels] = useState<FoundationModel[]>([]);
  // The default probe prompt follows the interface language; the user may of
  // course overwrite it with anything.
  const [prompt, setPrompt] = useState(() =>
    lang === "zh" ? "用一句话说明乙醇的分子式" : "State the molecular formula of ethanol in one sentence."
  );
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [providers, cfg, found] = await Promise.all([
        api.aiProviders(),
        api.aiConfig(),
        api.foundationModels(),
      ]);
      setState(providers);
      setConfig(cfg);
      setModels(found.models);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function chooseMode(mode: string) {
    try {
      const next = await api.setAiConfig({ mode });
      setConfig(next);
      pushLog(`$ ai mode -> ${mode}`);
      await refresh();
    } catch (err) {
      pushLog(`! ${(err as Error).message}`);
    }
  }

  async function send() {
    if (!prompt.trim()) return;
    setBusy(true);
    setReply("");
    try {
      const result = await api.aiComplete(prompt);
      setReply(
        `${result.text}\n\n[${translate(lang, "aiEngine")}=${result.engine} · ${translate(
          lang,
          "aiLatency"
        )}=${result.latency_ms.toFixed(0)} ms${result.model ? ` · ${result.model}` : ""}]`
      );
      pushLog(`$ ai.complete -> ${result.engine}`);
    } catch (err) {
      setReply(`! ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const mode = config?.mode ?? "auto";

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-slate-200">{translate(lang, "aiPanel")}</h2>
        <p className="mt-0.5 text-[10px] text-slate-500">
          {translate(lang, "aiMode")}: <span className="text-accent">{mode}</span>
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {error && <p className="mb-2 text-[11px] text-bad">{error}</p>}

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "aiMode")}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {["auto", "cloud", "local", "offline"].map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => chooseMode(item)}
                className={`rounded-md border px-2 py-1 text-[11px] transition ${
                  mode === item
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-line text-slate-300 hover:border-accent"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        </section>

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "aiProviders")} ({state?.available.length ?? 0}{" "}
            {translate(lang, "aiAvailable")})
          </h3>
          <ul className="space-y-1.5">
            {(state?.providers ?? []).map((provider) => (
              <li
                key={provider.name}
                className="rounded-md border border-line bg-canvas px-2 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      provider.available ? "bg-good" : "bg-slate-600"
                    }`}
                  />
                  <span className="text-[11px] font-medium text-slate-200">
                    {provider.name}
                  </span>
                  <span className="rounded bg-line px-1 text-[9px] text-slate-400">
                    {provider.family}
                  </span>
                  <span className="ml-auto font-mono text-[9px] text-slate-500">
                    {provider.model}
                  </span>
                </div>
                {!provider.available && provider.reason && (
                  <p className="mt-0.5 pl-3.5 text-[9px] text-slate-500">{provider.reason}</p>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-4">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "aiTest")}
          </h3>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={2}
            placeholder={translate(lang, "aiPromptHint")}
            className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-slate-200 outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={send}
            disabled={busy}
            className="mt-2 rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-canvas hover:bg-accent/85 disabled:opacity-40"
          >
            {busy ? translate(lang, "aiSending") : translate(lang, "aiTest")}
          </button>
          {reply && (
            <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-canvas p-2 text-[10px] leading-relaxed text-slate-300">
              {reply}
            </pre>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
            {translate(lang, "foundationModels")} ({models.length})
          </h3>
          <ul className="space-y-1.5">
            {models.map((model) => (
              <li
                key={model.key}
                className="rounded-md border border-line bg-canvas px-2 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-good" />
                  <span className="text-[11px] font-medium text-slate-200">{model.name}</span>
                  <span className="rounded bg-line px-1 text-[9px] text-slate-400">
                    {model.modality}
                  </span>
                  <span className="ml-auto font-mono text-[9px] text-slate-500">
                    {model.dimension} {translate(lang, "foundationDim")}
                  </span>
                </div>
                <p className="mt-0.5 text-[9px] leading-snug text-slate-500">
                  {model.family}
                  {model.requires_weights
                    ? ` · ${translate(lang, "foundationWeights")}`
                    : ` · ${translate(lang, "foundationLocal")}`}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
