/** Dock "Spectra" tab — plots every Spectrum produced by the last run.
 *
 * The mass-spectrum variant renders a ComfyUI-style stick plot (centroid
 * spectra draw vertical lines from zero, profile spectra draw a polyline),
 * everything else falls back to a connected line chart.  Colours come from the
 * active theme tokens, so the chart follows the wb-dark / wb-light switch.
 */

import { useMemo, useState } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { extractSpectra, isMassSpectrum, type SpectrumLike } from "../spectra";

const W = 720;
const H = 320;
const M = { top: 14, right: 16, bottom: 34, left: 56 };

function niceTicks(min: number, max: number, count = 8): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return [min];
  }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? mag * 10;
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step * 1e-6; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function SpectrumPlot({ spectrum }: { spectrum: SpectrumLike }) {
  const { theme } = useEditor();
  const dark = theme === "wb-dark";

  const model = useMemo(() => {
    const xs = (spectrum.x ?? []).filter((v) => Number.isFinite(v));
    const ysRaw = (spectrum.y ?? []).filter((v) => Number.isFinite(v));
    const n = Math.min(xs.length, ysRaw.length);
    const xsN = xs.slice(0, n);
    const ysN = ysRaw.slice(0, n);
    const xmax = xsN.length ? Math.max(...xsN) : 1;
    const xmin = xsN.length ? Math.min(...xsN) : 0;
    const ymax = ysN.length ? Math.max(...ysN) : 1;
    const padX = (xmax - xmin) * 0.02 || 1;
    return {
      xs: xsN,
      ys: ysN,
      xmin: Math.max(0, xmin - padX),
      xmax: xmax + padX,
      ymax: ymax || 1,
      centroid: (spectrum.peaks?.length ?? 0) > 0 && xsN.length < 2000,
    };
  }, [spectrum]);

  const px = (v: number) =>
    M.left + ((v - model.xmin) / (model.xmax - model.xmin || 1)) * (W - M.left - M.right);
  const py = (v: number) =>
    H - M.bottom - (v / model.ymax) * (H - M.top - M.bottom);

  const xTicks = niceTicks(model.xmin, model.xmax);
  const yTicks = niceTicks(0, model.ymax, 4);
  const axis = dark ? "rgb(var(--c-text-dim))" : "rgb(var(--c-text-dim))";
  const stroke = "rgb(var(--c-accent))";

  const paths = useMemo(() => {
    if (!model.xs.length) return { sticks: "", profile: "" };
    if (model.centroid) {
      let d = "";
      for (let i = 0; i < model.xs.length; i += 1) {
        const x = px(model.xs[i]);
        d += `M${x.toFixed(1)} ${py(0).toFixed(1)} L${x.toFixed(1)} ${py(model.ys[i]).toFixed(1)} `;
      }
      return { sticks: d.trim(), profile: "" };
    }
    const pts = model.xs.map((x, i) => `${px(x).toFixed(1)},${py(model.ys[i]).toFixed(1)}`);
    return { sticks: "", profile: `M${pts.join(" L")}` };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, theme]);

  const xUnit = spectrum.x_unit || (isMassSpectrum(spectrum) ? "m/z" : "");
  const yUnit = spectrum.y_unit || "";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full select-none" role="img">
      {/* grid + axes */}
      {yTicks.map((t) => (
        <g key={`y${t}`}>
          <line x1={M.left} x2={W - M.right} y1={py(t)} y2={py(t)} stroke={axis} strokeOpacity={0.18} />
          <text x={M.left - 6} y={py(t) + 3} textAnchor="end" fontSize="9" fill={axis}>
            {model.ymax > 1000 ? `${(t / 1000).toFixed(t % 1000 ? 1 : 0)}k` : t.toPrecision(3)}
          </text>
        </g>
      ))}
      {xTicks.map((t) => (
        <g key={`x${t}`}>
          <line x1={px(t)} x2={px(t)} y1={py(0)} y2={py(0) - 4} stroke={axis} />
          <text x={px(t)} y={H - M.bottom + 14} textAnchor="middle" fontSize="9" fill={axis}>
            {Math.abs(t) >= 1000 ? t.toFixed(0) : Number(t.toPrecision(4))}
          </text>
        </g>
      ))}
      <line x1={M.left} x2={W - M.right} y1={py(0)} y2={py(0)} stroke={axis} />
      <line x1={M.left} x2={M.left} y1={M.top} y2={py(0)} stroke={axis} />
      <text x={W - M.right} y={H - 4} textAnchor="end" fontSize="9" fill={axis}>
        {xUnit}
      </text>
      <text x={10} y={M.top + 4} fontSize="9" fill={axis}>
        {yUnit}
      </text>

      {paths.profile && (
        <path d={paths.profile} fill="none" stroke={stroke} strokeWidth={1.4} />
      )}
      {paths.sticks && (
        <path d={paths.sticks} fill="none" stroke={stroke} strokeWidth={1.1} strokeLinecap="round" />
      )}
    </svg>
  );
}

export default function PlotPanel() {
  const { lang, runResult, setDockTab } = useEditor();
  const spectra = useMemo(() => extractSpectra(runResult), [runResult]);
  const [selected, setSelected] = useState(0);

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

  const active = spectra[Math.min(selected, spectra.length - 1)].spectrum;
  const ms = isMassSpectrum(active);
  const topPeaks = [...(active.peaks ?? [])]
    .sort((a, b) => (b.y ?? 0) - (a.y ?? 0))
    .slice(0, 8);
  const base = topPeaks[0]?.y ?? 1;

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
            {translate(lang, "dockPlot")}
          </h2>
          <select
            value={Math.min(selected, spectra.length - 1)}
            onChange={(event) => setSelected(Number(event.target.value))}
            className="cml-widget max-w-44 font-mono text-[10px]"
          >
            {spectra.map((item, index) => (
              <option key={index} value={index}>
                {item.source}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-1 truncate text-[10px] text-[rgb(var(--c-text-faint))]">
          {active.name || "—"} · {active.mode || "?"} · {(active.x ?? []).length} pts
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        <div className="rounded border border-line bg-canvas p-1">
          <SpectrumPlot spectrum={active} />
        </div>

        <section className="mt-3">
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">
            {translate(lang, "plotTopPeaks")}
          </h3>
          <table className="w-full text-left text-[10px]">
            <thead>
              <tr className="text-[rgb(var(--c-text-faint))]">
                <th className="py-0.5 pr-2 font-medium">#</th>
                <th className="py-0.5 pr-2 font-medium">
                  {ms ? "m/z" : active.x_unit || "x"}
                </th>
                <th className="py-0.5 pr-2 font-medium">
                  {ms ? translate(lang, "plotIntensity") : active.y_unit || "y"}
                </th>
                <th className="py-0.5 font-medium">%</th>
              </tr>
            </thead>
            <tbody className="font-mono text-[rgb(var(--c-text-dim))]">
              {topPeaks.map((peak, index) => (
                <tr key={index} className="border-t border-line/60">
                  <td className="py-0.5 pr-2">{index + 1}</td>
                  <td className="py-0.5 pr-2">{(peak.x ?? 0).toFixed(4)}</td>
                  <td className="py-0.5 pr-2">{(peak.y ?? 0).toFixed(1)}</td>
                  <td className="py-0.5">{(((peak.y ?? 0) / base) * 100).toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <button
          type="button"
          onClick={() => setDockTab("inspector")}
          className="mt-3 w-full rounded border border-line px-2 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          {translate(lang, "plotBackToInspector")}
        </button>
      </div>
    </div>
  );
}
