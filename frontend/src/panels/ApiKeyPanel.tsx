/** API-key entry point (v0.7.3 task 1).
 *
 * The single place in the GUI where a secret is typed.  Three rules shape it:
 *
 *  1. **The storage choice is stated, not implied.**  The header names where a
 *     new key will land (OS keyring vs. a plain file) and says so out loud when
 *     that is a file.  A user who believes their key is encrypted should learn
 *     otherwise here rather than in a security incident.
 *  2. **A stored key is never rendered.**  The list shows the backend's mask
 *     (``sk-a•••••3456``), its length and where it came from.  Typing replaces
 *     it; there is no "reveal", because the backend never sends the value.
 *  3. **"Saved" is not "working".**  Saving pushes the value into the runtime
 *     environment, but only a probe proves the provider accepts it -- so the
 *     test button is a first-class action, not an afterthought.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type {
  CredentialProbe,
  CredentialProvider,
  CredentialStore,
  ProviderModelList,
} from "../types";

/** Which button is currently in flight, so one action's spinner is honest. */
type Pending = "" | "save" | "test" | "delete" | "models" | "model";

/** Localised pick from a backend bilingual map, falling back to English. */
function pick(map: Record<string, string> | undefined, lang: "zh" | "en"): string {
  if (!map) return "";
  return map[lang] || map.en || "";
}

/**
 * Colour a probe result by *what went wrong*, not merely by `ok` (v0.7.3).
 *
 * `invalid_key` is the user's key and gets the error colour.  A model the
 * endpoint does not carry, a rate limit and an unreachable host are all
 * failures the user cannot fix by re-typing the key, so they get the warning
 * colour instead -- otherwise a correct key behind a corporate proxy looks
 * exactly like a typo, and users learn to distrust the whole panel.
 *
 * Unknown outcomes fall back to `text-bad`: an unrecognised failure class is
 * not a reason to look calmer.
 */
function probeClass(probe: CredentialProbe): string {
  if (probe.ok) return "text-good";
  switch (probe.outcome) {
    case "model_unsupported":
    case "rate_limited":
    case "network_unreachable":
    case "timeout":
      return "text-warn";
    default:
      return "text-bad";
  }
}

export default function ApiKeyPanel() {
  const { lang, pushLog, setCredentialStatus } = useEditor();
  const [store, setStore] = useState<CredentialStore | null>(null);
  const [providers, setProviders] = useState<CredentialProvider[]>([]);
  const [selected, setSelected] = useState("");
  const [secret, setSecret] = useState("");
  const [reveal, setReveal] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [pending, setPending] = useState<Pending>("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [probe, setProbe] = useState<CredentialProbe | null>(null);
  const [models, setModels] = useState<ProviderModelList | null>(null);
  const [modelQuery, setModelQuery] = useState("");
  const [modelDraft, setModelDraft] = useState("");

  /**
   * A fetched listing belongs to the provider it was fetched from.  Keeping it
   * in state per selection means switching the picker can never leave NVIDIA's
   * 81 ids sitting under DeepSeek's name -- a list that looks authoritative
   * and is not.
   */
  const resetModels = useCallback(() => {
    setModels(null);
    setModelQuery("");
    setModelDraft("");
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [current, catalogue] = await Promise.all([
        api.credentials(),
        api.credentialProviders(),
      ]);
      setStore(current);
      setProviders(catalogue.providers);
      setError("");
      // Publish to the store so the top bar badge agrees with this panel.
      setCredentialStatus(
        current.credentials.filter((item) => item.configured).map((item) => item.provider)
      );
      setSelected((prev) => {
        if (prev && current.credentials.some((item) => item.provider === prev)) return prev;
        // Default to the first cloud provider without a key -- that is almost
        // always the one the user came here to add.
        const unconfigured = current.credentials.find(
          (item) => !item.configured && item.kind === "cloud"
        );
        return unconfigured?.provider ?? current.credentials[0]?.provider ?? "";
      });
    } catch (err) {
      setError((err as Error).message);
    }
  }, [setCredentialStatus]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const status = useMemo(
    () => store?.credentials.find((item) => item.provider === selected) ?? null,
    [store, selected]
  );
  const provider = useMemo(
    () => providers.find((item) => item.id === selected) ?? null,
    [providers, selected]
  );

  // A probe result belongs to the provider it was made against; switching the
  // picker must not leave a green tick sitting next to the wrong row.
  useEffect(() => {
    setProbe(null);
    setNotice("");
    setSecret("");
    setBaseUrl("");
    resetModels();
  }, [selected, resetModels]);

  function reset() {
    setSecret("");
    setReveal(false);
    setBaseUrl("");
    setProbe(null);
    setNotice("");
    setError("");
    resetModels();
  }

  async function save() {
    if (!selected) return;
    if (!secret.trim()) {
      setError(translate(lang, "keyEmpty"));
      return;
    }
    setPending("save");
    setError("");
    try {
      const result = await api.setCredential(selected, secret, baseUrl.trim());
      setStore(result.status);
      setCredentialStatus(
        result.status.credentials.filter((item) => item.configured).map((item) => item.provider)
      );
      const where = result.stored_in ?? "environment";
      setNotice(translate(lang, "keySaved").replace("{where}", where));
      setSecret("");
      setReveal(false);
      pushLog(`$ credential stored: ${selected} -> ${where}`);
    } catch (err) {
      setError((err as Error).message);
      pushLog(`! credential: ${(err as Error).message}`);
    } finally {
      setPending("");
    }
  }

  async function test() {
    if (!selected) return;
    setPending("test");
    setError("");
    setNotice("");
    try {
      const result = await api.testCredential(selected);
      setProbe(result);
      pushLog(
        `${result.ok ? "$" : "!"} credential test ${selected}: ${result.ok ? "ok" : result.detail}`
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending("");
    }
  }

  /**
 * Fetch the provider's own model catalogue.
 *
 * The result is labelled a catalogue everywhere it appears.  NVIDIA NIM answers
 * `/v1/models` with 81 ids while many of them return 410 on an actual call, so
 * showing this as "available models" would be a promise the provider never made.
 */
async function fetchModels() {
    if (!selected) return;
    setPending("models");
    setError("");
    try {
      const result = await api.providerModels(selected);
      setModels(result);
      setModelQuery("");
      // Seed the draft with what is stored, not with what was typed: the
      // stored value is what inference will use.
      setModelDraft(result.selected ?? "");
      if (result.ok) {
        pushLog(`$ model catalogue ${selected}: ${result.count ?? 0} id(s)`);
      } else {
        pushLog(`! model catalogue ${selected}: ${result.detail}`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending("");
    }
}

/** Remember the chosen id so nodes that name no model will use it. */
async function applyModel(model: string) {
    if (!selected) return;
    setPending("model");
    setError("");
    try {
      await api.setProviderModel(selected, model);
      const fresh = await api.credentials();
      setStore(fresh);
      setModels((prev) => (prev ? { ...prev, selected: model } : prev));
      setModelDraft(model);
      setNotice(
        model
          ? translate(lang, "keyModelSaved").replace("{model}", model)
          : translate(lang, "keyModelCleared")
      );
      pushLog(`$ model for ${selected}: ${model || "(default)"}`);
      // A probe made before the change describes a model no longer in use.
      setProbe(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending("");
    }
  }

  async function remove() {
    if (!selected) return;
    setPending("delete");
    setError("");
    try {
      const result = await api.deleteCredential(selected);
      setStore(result.status);
      setCredentialStatus(
        result.status.credentials.filter((item) => item.configured).map((item) => item.provider)
      );
      setNotice(result.removed ? translate(lang, "keyDeleted") : translate(lang, "keyAbsent"));
      pushLog(`$ credential removed: ${selected}`);
      reset();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending("");
    }
  }

  const backendLabel = pick(store?.backend_label, lang);
  const warning = store?.warning ? pick(store.warning, lang) : "";
  const envVar = status?.env_var || provider?.env_var || "";
  const docsUrl = status?.docs_url || provider?.docs_url || "";
  const note = pick(status?.notes ?? provider?.notes, lang);
  const defaultBase = status?.default_base_url || provider?.default_base_url || "";
  const defaultModel = provider?.probe_model || models?.default_model || "";
  const selectedModel = status?.selected_model || "";
  const hasCatalogue = provider?.has_catalogue ?? false;

  /**
   * Filter as the user types.  Substring rather than fuzzy: an 81-entry list
   * is short enough to scan, and a fuzzy matcher that reorders entries makes
   * it impossible to find an id you can already see.
   */
  const visibleModels = useMemo(() => {
    const all = models?.models ?? [];
    const query = modelQuery.trim().toLowerCase();
    if (!query) return all;
    return all.filter((item) => item.id.toLowerCase().includes(query));
  }, [models, modelQuery]);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
          {translate(lang, "keyPanel")}
        </h2>
        <p className="mt-0.5 text-[10px] leading-snug text-[rgb(var(--c-text-faint))]">
          {translate(lang, "keyPanelHint")}
        </p>
        <p className="mt-1.5 inline-flex items-center gap-1 rounded border border-line bg-canvas px-1.5 py-0.5 text-[9px] text-[rgb(var(--c-text-dim))]">
          {translate(lang, "keyBackend")}: <span className="text-accent">{backendLabel}</span>
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {warning && (
          <p className="mb-3 rounded-md border border-warn/40 bg-warn/10 px-2 py-1.5 text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
            {warning}
          </p>
        )}
        {error && <p className="mb-2 text-[11px] text-bad">{error}</p>}
        {notice && <p className="mb-2 text-[11px] text-good">{notice}</p>}

        {/* --- picker ------------------------------------------------------ */}
        <section className="mb-3">
          <label
            htmlFor="credential-provider"
            className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-accent/80"
          >
            {translate(lang, "keyProvider")}
          </label>
          <select
            id="credential-provider"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
          >
            {providers.map((item) => {
              const state = store?.credentials.find((c) => c.provider === item.id);
              return (
                <option key={item.id} value={item.id}>
                  {pick(item.labels, lang)}
                  {state?.configured ? `  ·  ${state.masked}` : ""}
                </option>
              );
            })}
          </select>
          {note && (
            <p className="mt-1 text-[9px] leading-snug text-[rgb(var(--c-text-faint))]">{note}</p>
          )}
        </section>

        {/* --- current state ----------------------------------------------- */}
        <section
          className={`mb-3 rounded-md border px-2 py-2 ${
            status?.configured ? "border-good/40 bg-good/5" : "border-line bg-canvas"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                status?.configured ? "bg-good" : "bg-line"
              }`}
            />
            <span className="text-[11px] font-medium text-[rgb(var(--c-text))]">
              {status?.configured ? translate(lang, "keyConfigured") : translate(lang, "keyMissing")}
            </span>
            {envVar && (
              <span className="ml-auto font-mono text-[9px] text-[rgb(var(--c-text-faint))]">
                {envVar}
              </span>
            )}
          </div>
          {status?.configured && (
            <p className="mt-1 font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
              {status.masked}
              <span className="ml-1.5 text-[9px] text-[rgb(var(--c-text-faint))]">
                {translate(lang, "keySource")}: {status.source} · {status.length}{" "}
                {translate(lang, "keyChars")}
              </span>
            </p>
          )}
          {status?.configured && !probe && (
            <p className="mt-1 text-[9px] leading-snug text-[rgb(var(--c-text-faint))]">
              {translate(lang, "keyStoredHint")}
            </p>
          )}
          {probe && (
            <p
              className={`mt-1.5 text-[10px] leading-snug ${
                probeClass(probe)
              }`}
            >
              {/* v0.7.3: colour by failure class, not by ok/false. A rejected
                  key and an unreachable host are both "not ok", but only one
                  of them is fixed by editing the key -- painting both red
                  taught users to ignore the red. */}
              {probe.ok ? translate(lang, "keyTestOk") : probe.detail}
              {probe.ok && probe.model ? ` · ${probe.model}` : ""}
              {!probe.ok && probe.base_url ? (
                <span className="ml-1 opacity-70">{probe.base_url}</span>
              ) : null}
            </p>
          )}
        </section>

        {/* --- entry -------------------------------------------------------- */}
        <section className="mb-3">
          <label
            htmlFor="credential-secret"
            className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-accent/80"
          >
            {status?.configured ? translate(lang, "keyReplace") : translate(lang, "keyEnter")}
          </label>
          <div className="relative">
            <input
              id="credential-secret"
              type={reveal ? "text" : "password"}
              value={secret}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setSecret(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") save();
              }}
              placeholder={translate(lang, "keyPlaceholder")}
              className="w-full rounded-md border border-line bg-canvas py-1.5 pl-2 pr-14 font-mono text-[11px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => setReveal((prev) => !prev)}
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[9px] text-[rgb(var(--c-text-faint))] transition hover:text-accent"
            >
              {reveal ? translate(lang, "keyHide") : translate(lang, "keyShow")}
            </button>
          </div>
          {(provider?.kind === "local" || defaultBase) && (
            <input
              type="text"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={defaultBase || translate(lang, "keyBaseUrlHint")}
              className="mt-1.5 w-full rounded-md border border-line bg-canvas px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
            />
          )}
          {docsUrl && (
            <a
              href={docsUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1.5 inline-block text-[9px] text-accent underline underline-offset-2"
            >
              {translate(lang, "keyDocs")}
            </a>
          )}
        </section>

        {/* --- model catalogue ---------------------------------------------- */}
        <section className="mb-3 rounded-md border border-line bg-canvas px-2 py-2">
          <div className="flex items-center gap-2">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-accent/80">
              {translate(lang, "keyModelTitle")}
            </label>
            {hasCatalogue && (
              <button
                type="button"
                onClick={fetchModels}
                disabled={pending !== "" || !selected}
                className="ml-auto rounded border border-line px-2 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-accent disabled:opacity-40"
              >
                {pending === "models"
                  ? translate(lang, "keyModelFetching")
                  : models
                    ? translate(lang, "keyModelRefresh")
                    : translate(lang, "keyModelFetch")}
              </button>
            )}
          </div>

          {/* What will actually be sent, stated before anything is fetched. */}
          <p className="mt-1.5 text-[10px] leading-snug text-[rgb(var(--c-text-dim))]">
            {selectedModel ? (
              <span className="font-mono text-accent">{selectedModel}</span>
            ) : defaultModel ? (
              <span className="font-mono">{defaultModel}</span>
            ) : (
              <span className="text-[rgb(var(--c-text-faint))]">—</span>
            )}
            <span className="ml-1 text-[9px] text-[rgb(var(--c-text-faint))]">
              {selectedModel
                ? `· ${translate(lang, "keyModelCurrent")}`
                : defaultModel
                  ? `· ${translate(lang, "keyModelDefault")}`
                  : ""}
            </span>
          </p>

          {models && (
            <p
              className={`mt-1 text-[9px] leading-snug ${
                models.ok ? "text-[rgb(var(--c-text-faint))]" : "text-warn"
              }`}
            >
              {models.detail}
            </p>
          )}
          {!models && hasCatalogue && (
            <p className="mt-1 text-[9px] leading-snug text-[rgb(var(--c-text-faint))]">
              {translate(lang, "keyModelPickFirst")}
            </p>
          )}
          {!hasCatalogue && (
            <p className="mt-1 text-[9px] leading-snug text-[rgb(var(--c-text-faint))]">
              {translate(lang, "keyModelNoneOffered")}
            </p>
          )}

          {/* A hand-typed id always stays reachable: the catalogue is not
              authoritative (NVIDIA lists retired ids), so the model a user
              knows works may be absent from it.  Kept as a draft -- writing on
              every keystroke would fire a request per character. */}
          <div className="mt-1.5 flex gap-1">
            <input
              type="text"
              value={modelDraft}
              placeholder={translate(lang, "keyModelPlaceholder")}
              onChange={(event) => setModelDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") applyModel(modelDraft.trim());
              }}
              className="min-w-0 flex-1 rounded-md border border-line bg-panel px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={() => applyModel(modelDraft.trim())}
              disabled={pending === "model" || modelDraft.trim() === selectedModel}
              title={translate(lang, "keyModelApply")}
              className="shrink-0 rounded-md border border-line px-2 py-1 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-accent disabled:opacity-40"
            >
              {pending === "model" ? "…" : translate(lang, "keyModelApply")}
            </button>
          </div>

          {models?.ok && (
            <>
              <input
                type="text"
                value={modelQuery}
                onChange={(event) => setModelQuery(event.target.value)}
                placeholder={translate(lang, "keyModelFilter")}
                className="mt-1.5 w-full rounded-md border border-line bg-panel px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
              />
              <select
                value=""
                onChange={(event) => {
                  if (event.target.value) {
                    setModelDraft(event.target.value);
                    applyModel(event.target.value);
                  }
                }}
                size={visibleModels.length > 12 ? 12 : Math.max(visibleModels.length, 3)}
                className="mt-1.5 w-full rounded-md border border-line bg-panel px-2 py-1 font-mono text-[10px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
              >
                {visibleModels.length === 0 ? (
                  <option value="">
                    {translate(lang, "keyModelSearchNone").replace("{query}", modelQuery)}
                  </option>
                ) : (
                  visibleModels.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id}
                      {item.id === selectedModel ? `  · ${translate(lang, "keyModelCurrent")}` : ""}
                      {item.id === defaultModel && item.id !== selectedModel
                        ? `  · ${translate(lang, "keyModelDefault")}`
                        : ""}
                      {item.detail ? `  · ${item.detail}` : ""}
                    </option>
                  ))
                )}
              </select>
              <p className="mt-1 text-[9px] text-[rgb(var(--c-text-faint))]">
                {translate(lang, "keyModelCount").replace(
                  "{count}",
                  String(models.total ?? models.count ?? 0)
                )}
                {models.truncated ? ` · ${models.count}/${models.total}` : ""}
              </p>
            </>
          )}

          {/* v0.7.3: the catalogue is explicitly not an availability promise.
              NVIDIA lists 81 ids of which many answer 410, so this note stays
              on screen next to the picker rather than in a footnote. */}
          {models?.ok && (
            <p className="mt-1 text-[9px] leading-relaxed text-[rgb(var(--c-text-faint))]">
              {translate(lang, "keyModelNote")}
            </p>
          )}
          {selectedModel && (
            <p className="mt-1 text-[9px] text-[rgb(var(--c-text-faint))]">
              {translate(lang, "keyModelSavedHint")}
            </p>
          )}
        </section>

        {/* --- actions ------------------------------------------------------ */}
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={save}
            disabled={pending !== "" || !selected}
            className="rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-canvas transition hover:bg-accent/85 disabled:opacity-40"
          >
            {pending === "save" ? translate(lang, "keySaving") : translate(lang, "keySave")}
          </button>
          <button
            type="button"
            onClick={test}
            disabled={pending !== "" || !selected}
            className="rounded-md border border-line px-3 py-1.5 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-accent disabled:opacity-40"
          >
            {pending === "test" ? translate(lang, "keyTesting") : translate(lang, "keyTest")}
          </button>
          <button
            type="button"
            onClick={remove}
            disabled={pending !== "" || !status?.configured}
            className="rounded-md border border-line px-3 py-1.5 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-bad hover:text-bad disabled:opacity-40"
          >
            {pending === "delete" ? translate(lang, "keyDeleting") : translate(lang, "keyDelete")}
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={pending !== ""}
            title={translate(lang, "keyRefresh")}
            className="rounded-md border border-line px-2 py-1.5 text-[11px] text-[rgb(var(--c-text-faint))] transition hover:border-accent hover:text-accent disabled:opacity-40"
          >
            ↻
          </button>
        </div>

        <p className="mt-3 text-[9px] leading-relaxed text-[rgb(var(--c-text-faint))]">
          {translate(lang, "keyFootnote")}
        </p>
      </div>
    </div>
  );
}