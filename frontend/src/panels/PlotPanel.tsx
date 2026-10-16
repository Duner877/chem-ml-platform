/** Dock "Spectra" tab — plots every Spectrum produced by the last run.
 *
 * Layout top→bottom: spectrum selector, the plot (click to enlarge), the major
 * peak table, and — for mass spectra — the fragmentation-pathway deduction
 * window driven by the AI assistant.
 *
 * The plot itself lives in :mod:`../components/SpectrumLightbox` so the dock
 * and the full-window lightbox render exactly the same trace.
 */

import { useMemo, useState } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { extractSpectra, isMassSpectrum, type SpectrumLike } from "../spectra";
import SpectrumLightbox, { SpectrumPlot } from "../components/SpectrumLightbox";
import FragmentationPanel from "../components/FragmentationPanel";
import { IconZoom } from "../components/Icons";
import type { RunResult } from "../types";

/** Pull the best available candidate SMILES out of a run result. */
function candidateSmiles(result: RunResult | null): string {
  if (!result?.records) return "";
  let best = "";
  let bestScore = -1;
  for (const record of Object.values(result.records)) {
    for (const value of Object.values(record.outputs ?? {})) {
      const stack: unknown[] = [value];
      while (stack.length) {
        const item = stack.pop();
        if (Array.isArray(item)) {
          stack.push(...item);
          continue;
        }
        if (typeof item !== "object" || item === null) continue;
        const payload = item as Record<string, unknown>;
        if (payload.type === "Molecule") {
          const smiles = String(payload.smiles ?? "").trim();
          const properties = (payload.properties ?? {}) as Record<string, unknown>;
          const score = Number(properties.confidence ?? 0) || 0;
          if (smiles && score >= bestScore) {
            bestScore = score;
            best = smiles;
          }
        }
        for (const nested of Object.values(payload)) {
          if (Array.isArray(nested) || (typeof nested === "object" && nested !== null)) {
            stack.push(nested);
          }
        }
      }
    }
  }
  return best;
}

function header(active: SpectrumLike, lang: "zh" | "en") {
  const parts = [
    active.name || "—",
    // v0.7.2: this used to fall back to a bare "?" when the mode was unset,
    // which read as an error.  An explicit "unlabelled" says what it means.
    active.mode || translate(lang, "unlabelled"),
    `${(active.x ?? []).length} pts`,
  ];
  if (active.ms_level) parts.push(`MS${active.ms_level}`);
  if (active.polarity) parts.push(active.polarity);
  if (active.precursor_mz) parts.push(`precursor ${active.precursor_mz}`);
  return parts.join(" · ");
}

export default function PlotPanel() {
  const { lang, runResult, setDockTab } = useEditor();
  const spectra = useMemo(() => extractSpectra(runResult), [runResult]);
  const smiles = useMemo(() => candidateSmiles(runResult), [runResult]);
  const [selected, setSelected] = useState(0);
  const [enlarged, setEnlarged] = useState(false);

  if (!runResult) {
    return (
      <div className="flex h-full flex-col">
        <header className="border-b border-line px-3 py-3">
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "dockPlot")}
          </h2>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-3xl">📈</div>
          <p className="text-xs text-[rgb(var(--c-text-faint))]">
            {translate(lang, "plotRunFirst")}
          </p>
        </div>
      </div>
    );
  }

  if (spectra.length === 0) {
    return (
      <div className="flex h-full flex-col">
        <header className="border-b border-line px-3 py-3">
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "dockPlot")}
          </h2>
        </header>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-3xl">📉</div>
          <p className="text-xs text-[rgb(var(--c-text-faint))]">
            {translate(lang, "plotNoSpectrum")}
          </p>
        </div>
      </div>
    );
  }

  const index = Math.min(selected, spectra.length - 1);
  const active = spectra[index].spectrum;
  const ms = isMassSpectrum(active);
  const topPeaks = [...(active.peaks ?? [])]
    .sort((a, b) => (b.y ?? 0) - (a.y ?? 0))
    .slice(0, 8);
  const base = topPeaks[0]?.y ?? 1;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "dockPlot")}
          </h2>
          <select
            value={index}
            onChange={(event) => setSelected(Number(event.target.value))}
            className="cml-widget max-w-44 font-mono text-[10px]"
          >
            {spectra.map((item, position) => (
              <option key={position} value={position}>
                {item.source}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-1 truncate text-[10px] text-[rgb(var(--c-text-faint))]">
          {header(active, lang)}
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {/* click-to-enlarge ------------------------------------------------ */}
        <div className="group relative rounded border border-line bg-canvas p-1">
          <button
            type="button"
            onClick={() => setEnlarged(true)}
            title={translate(lang, "plotEnlarge")}
            className="block w-full cursor-zoom-in"
          >
            <SpectrumPlot spectrum={active} />
          </button>
          <button
            type="button"
            onClick={() => setEnlarged(true)}
            title={translate(lang, "plotEnlarge")}
            className="absolute right-2 top-2 flex items-center gap-1 rounded border border-line bg-panel px-1.5 py-0.5 text-[9px] text-[rgb(var(--c-text-dim))] opacity-0 transition group-hover:opacity-100 hover:text-[rgb(var(--c-text))]"
          >
            <IconZoom size={11} />
            {translate(lang, "plotEnlarge")}
          </button>
        </div>

        {/* major peaks ------------------------------------------------------ */}
        <section className="mt-3">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[rgb(var(--c-text-dim))]">
            {translate(lang, "plotTopPeaks")}
          </h3>
          <table className="w-full text-left text-[10px]">
            <thead>
              <tr className="text-[rgb(var(--c-text-faint))]">
                <th className="py-0.5 pr-2 font-medium">#</th>
                <th className="py-0.5 pr-2 font-medium">{ms ? "m/z" : active.x_unit || "x"}</th>
                <th className="py-0.5 pr-2 font-medium">
                  {ms ? translate(lang, "plotIntensity") : active.y_unit || "y"}
                </th>
                <th className="py-0.5 font-medium">%</th>
              </tr>
            </thead>
            <tbody className="font-mono text-[rgb(var(--c-text-dim))]">
              {topPeaks.map((peak, peakIndex) => (
                <tr key={peakIndex} className="border-t border-line/60">
                  <td className="py-0.5 pr-2">{peakIndex + 1}</td>
                  <td className="py-0.5 pr-2">{(peak.x ?? 0).toFixed(4)}</td>
                  <td className="py-0.5 pr-2">{(peak.y ?? 0).toFixed(1)}</td>
                  <td className="py-0.5">{(((peak.y ?? 0) / base) * 100).toFixed(1)}</td>
                </tr>
              ))}
              {topPeaks.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-2 text-[rgb(var(--c-text-faint))]">
                    {translate(lang, "plotNoPeaks")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>

        {/* fragmentation pathway (mass spectra only) ----------------------- */}
        {ms && (
          <FragmentationPanel spectrum={active} smiles={smiles} />
        )}

        <button
          type="button"
          onClick={() => setDockTab("inspector")}
          className="mt-3 w-full rounded border border-line px-2 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          {translate(lang, "plotBackToInspector")}
        </button>
      </div>

      {enlarged && (
        <SpectrumLightbox
          spectrum={active}
          title={`${spectra[index].source} — ${
            active.name || translate(lang, "dockPlot")
          }`}
          onClose={() => setEnlarged(false)}
        />
      )}
    </div>
  );
}