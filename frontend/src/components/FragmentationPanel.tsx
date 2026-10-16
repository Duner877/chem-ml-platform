/** Fragmentation-pathway deduction window (v0.7.2).
 *
 * Sits below the "Top peaks" table in the Spectra dock and answers the question
 * a peak list alone cannot: *why* are these peaks there?
 *
 * The work is split the same way the backend splits it:
 *
 * * the **rule engine** (a real backend call) produces the pathway -- which
 *   peak, which cleavage or neutral loss, what mass error, what confidence;
 * * the **AI assistant** interprets that evidence chain.
 *
 * When no AI provider is reachable the panel still shows the pathway and says
 * so in the engine badge, because the deduction does not need a model.  The
 * badge is the whole point: a rules answer and a model answer must never look
 * the same.
 */

import { useCallback, useState } from "react";
import { api } from "../api";
import { translate } from "../i18n";
import { useEditor } from "../store";
import type { SpectrumLike } from "../spectra";
import type { FragmentationResult } from "../types";
import { IconBranch, IconSparkle } from "./Icons";

/** True when the narrative was written by a real model, not the rules engine. */
function isModelNarrative(engine: string): boolean {
  return engine.startsWith("external:");
}

/** Column index lookup so the table stays readable if columns are reordered. */
function columnIndex(columns: string[], ...names: string[]): number {
  for (const name of names) {
    const index = columns.findIndex((column) => column.toLowerCase() === name);
    if (index >= 0) return index;
  }
  return -1;
}

export default function FragmentationPanel({
  spectrum,
  smiles,
}: {
  spectrum: SpectrumLike;
  /** Candidate structure from the run result, when one was identified. */
  smiles?: string;
}) {
  const { lang } = useEditor();
  const [result, setResult] = useState<FragmentationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [useAi, setUseAi] = useState(true);

  const deduce = useCallback(
    async (withAi: boolean) => {
      setBusy(true);
      setError("");
      try {
        const payload = await api.fragmentationPathway({
          spectrum,
          smiles: smiles ?? "",
          use_ai: withAi,
          language: lang === "en" ? "en" : "zh",
        });
        setResult(payload);
        setUseAi(withAi);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [spectrum, smiles, lang]
  );

  const columns = result?.columns ?? [];
  const idx = {
    step: columnIndex(columns, "step"),
    rule: columnIndex(columns, "rule"),
    fragment: columnIndex(columns, "fragment"),
    mz: columnIndex(columns, "observed m/z"),
    loss: columnIndex(columns, "loss (da)"),
    relative: columnIndex(columns, "rel. %"),
    error: columnIndex(columns, "error (ppm)"),
    confidence: columnIndex(columns, "confidence"),
  };

  const rows = result?.pathway ?? [];
  const cell = (row: unknown[], index: number) =>
    index >= 0 ? (row[index] as string | number | undefined) : undefined;

  const modelNarrative = result ? isModelNarrative(result.ai_engine) : false;

  return (
    <section className="mt-4 border-t border-line pt-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[rgb(var(--c-text-dim))]">
          <IconBranch size={13} />
          {translate(lang, "fragTitle")}
        </h3>
        <div className="flex items-center gap-1.5">
          <label className="flex items-center gap-1 text-[10px] text-[rgb(var(--c-text-faint))]">
            <input
              type="checkbox"
              checked={useAi}
              onChange={(event) => setUseAi(event.target.checked)}
              className="h-3 w-3 accent-[rgb(var(--c-accent))]"
            />
            {translate(lang, "fragUseAi")}
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => void deduce(useAi)}
            className="flex items-center gap-1 rounded border border-line px-2 py-1 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))] disabled:opacity-40"
          >
            <IconSparkle size={11} />
            {busy
              ? translate(lang, "fragRunning")
              : result
                ? translate(lang, "fragRedo")
                : translate(lang, "fragRun")}
          </button>
        </div>
      </div>

      <p className="mt-1 text-[10px] leading-relaxed text-[rgb(var(--c-text-faint))]">
        {smiles
          ? lang === "en"
            ? `Candidate structure ${smiles} — the search proposes cleavages this structure actually permits.`
            : `候选结构 ${smiles} —— 推导只提出该结构在化学上允许的断键方式。`
          : lang === "en"
            ? "No structure available: only neutral-loss relationships between the observed peaks are reported. No bond is inferred."
            : "暂无结构信息：只报告观测峰之间的中性丢失关系，不推断任何化学键。"}
      </p>

      {error && (
        <p className="mt-2 rounded border border-bad/40 bg-bad/10 px-2 py-1 text-[10px] text-bad">
          {error}
        </p>
      )}

      {!result && !error && !busy && (
        <p className="mt-2 rounded border border-line px-2 py-2 text-center text-[10px] text-[rgb(var(--c-text-faint))]">
          {translate(lang, "fragIdle")}
        </p>
      )}

      {result && (
        <>
          {/* engine provenance -- never hide which engine answered */}
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[9px]">
            <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[rgb(var(--c-text-dim))]">
              {result.engine}
            </span>
            <span
              className={`rounded border px-1.5 py-0.5 font-mono ${
                modelNarrative
                  ? "border-good/40 text-good"
                  : "border-line text-[rgb(var(--c-text-faint))]"
              }`}
              title={
                modelNarrative
                  ? lang === "en"
                    ? "written by a language model"
                    : "由大模型生成"
                  : lang === "en"
                    ? "no AI provider was reachable — the built-in rule engine answered"
                    : "没有可用的 AI 供应商，由内置规则引擎作答"
              }
            >
              {result.ai_engine}
            </span>
            <span className="text-[rgb(var(--c-text-faint))]">
              {lang === "en" ? "confidence" : "置信度"}{" "}
              <span className="font-mono text-[rgb(var(--c-text-dim))]">
                {Number(result.confidence || 0).toFixed(3)}
              </span>
            </span>
            {typeof result.metadata?.precursor_mz === "number" && (
              <span
                className="text-[rgb(var(--c-text-faint))]"
                title={
                  lang === "en"
                    ? "Where the precursor came from: declared by the measurement, computed from the candidate structure, or guessed from the base peak"
                    : "前体离子来源：测量声明、由候选结构推算，或由基质峰猜测"
                }
              >
                {lang === "en" ? "precursor" : "前体"} m/z{" "}
                <span className="font-mono text-[rgb(var(--c-text-dim))]">
                  {result.metadata.precursor_mz.toFixed(4)}
                </span>
                {result.metadata.precursor_source && (
                  <span className="ml-1 opacity-70">
                    ({result.metadata.precursor_source})
                  </span>
                )}
              </span>
            )}
          </div>

          {/* The de-adducted molecule ion is observed but breaks no bond: the
              engine keeps it out of the numbered pathway on purpose. */}
          {result.metadata?.de_adducted && (
            <p className="mt-1.5 rounded border border-line bg-panel2/40 px-2 py-1 text-[9px] leading-relaxed text-[rgb(var(--c-text-faint))]">
              {lang === "en" ? "Also observed: de-adducted molecule ion at m/z " : "另观测到去加合分子离子 m/z "}
              <span className="font-mono text-[rgb(var(--c-text-dim))]">
                {Number(result.metadata.de_adducted.observed_mz ?? 0).toFixed(4)}
              </span>
              {lang === "en"
                ? " — it breaks no bond, so it is not counted as a fragmentation step."
                : " —— 它未断开任何化学键，故不计入裂解步骤。"}
            </p>
          )}

          {rows.length === 0 ? (
            <p className="mt-2 rounded border border-line px-2 py-2 text-[10px] text-[rgb(var(--c-text-faint))]">
              {lang === "en"
                ? "No theoretical fragment matched an observed peak within the tolerance."
                : "在给定容差内没有理论碎片与观测峰匹配。"}
            </p>
          ) : (
            <ol className="mt-2 space-y-1">
              {rows.map((row, rowIndex) => {
                const confidence = Number(cell(row, idx.confidence) ?? 0);
                const rule = String(cell(row, idx.rule) ?? "");
                // A ladder label looks like "-H2O-CH3"; render the steps as a
                // chain so it reads as a pathway rather than a formula.
                const ladder = rule.includes("-", 1)
                  ? rule
                      .slice(1)
                      .split("-")
                      .filter(Boolean)
                      .join(" → -")
                  : rule;
                const fragment = String(cell(row, idx.fragment) ?? "");
                const rationale = String(row[row.length - 1] ?? "");
                return (
                  <li
                    key={rowIndex}
                    className="rounded border border-line bg-panel2/40 px-2 py-1.5"
                  >
                    <div className="flex items-center gap-2">
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-line font-mono text-[9px] text-[rgb(var(--c-text-dim))]">
                        {cell(row, idx.step) ?? rowIndex + 1}
                      </span>
                      <span className="truncate text-[11px] text-[rgb(var(--c-text))]">
                        {ladder}
                        {fragment && !rule.includes(fragment) ? (
                          <span className="ml-1.5 font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
                            {fragment}
                          </span>
                        ) : null}
                      </span>
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
                        {Number(cell(row, idx.mz) ?? 0).toFixed(4)}
                      </span>
                      {/* confidence as a bar, so the ranking is readable */}
                      <span
                        className="h-1 w-10 shrink-0 overflow-hidden rounded-full bg-line"
                        title={`${(confidence * 100).toFixed(0)}%`}
                      >
                        <span
                          className="block h-full bg-[rgb(var(--c-text-dim))]"
                          style={{ width: `${Math.round(confidence * 100)}%` }}
                        />
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-x-3 pl-6 font-mono text-[9px] text-[rgb(var(--c-text-faint))]">
                      <span>
                        {lang === "en" ? "loss" : "丢失"} {Number(cell(row, idx.loss) ?? 0).toFixed(4)}{" "}
                        Da
                      </span>
                      <span>
                        {lang === "en" ? "rel" : "相对"} {Number(cell(row, idx.relative) ?? 0).toFixed(1)}%
                      </span>
                      <span>
                        {lang === "en" ? "error" : "误差"}{" "}
                        {Number(cell(row, idx.error) ?? 0).toFixed(2)} ppm
                      </span>
                    </div>
                    {rationale && (
                      <p className="mt-0.5 pl-6 text-[9px] leading-relaxed text-[rgb(var(--c-text-faint))]">
                        {rationale}
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}

          {result.narrative && (
            <div className="mt-2">
              <h4 className="mb-1 text-[10px] font-semibold text-[rgb(var(--c-text-dim))]">
                {modelNarrative
                  ? translate(lang, "fragAiReading")
                  : translate(lang, "fragRulesReading")}
              </h4>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded border border-line bg-panel2/40 px-2 py-1.5 font-sans text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
                {result.narrative}
              </pre>
            </div>
          )}
        </>
      )}
    </section>
  );
}