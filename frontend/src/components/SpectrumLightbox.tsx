/** Spectrum lightbox — click any plot to enlarge it (v0.7.2).
 *
 * The dock is ~18rem wide, which is enough to see that a spectrum exists and
 * roughly where its peaks are, but not enough to read an m/z axis.  Clicking
 * the plot opens the same trace full-window with wheel zoom, drag pan and a
 * peak readout, and closes on Escape / backdrop click / the close button.
 *
 * Rendering is shared with the dock (:func:`SpectrumPlot`) so the enlarged view
 * can never disagree with the small one.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { translate } from "../i18n";
import { useEditor } from "../store";
import { resolveTheme } from "../theme";
import { isMassSpectrum, type SpectrumLike } from "../spectra";
import { IconMinus, IconPlus } from "../components/Icons";

/** Plot geometry — shared with the dock so both views agree exactly. */
export const PLOT_W = 720;
export const PLOT_H = 320;
export const PLOT_M = { top: 14, right: 16, bottom: 34, left: 56 };

/** Nice round tick positions between ``min`` and ``max``. */
export function niceTicks(min: number, max: number, count = 8): number[] {
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

export interface PlotModel {
  xs: number[];
  ys: number[];
  /** One entry per band; empty for an ordinary single-trace spectrum. */
  bands: number[][];
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
  centroid: boolean;
}

/** Reduce a spectrum to plottable arrays plus the axis range. */
export function buildModel(spectrum: SpectrumLike): PlotModel {
  const xs = (spectrum.x ?? []).filter((v) => Number.isFinite(v));
  // A band structure arrives as ``curves`` with ``y`` empty.  Falling back to
  // ``y`` first would draw the empty panel the old flattening produced, and
  // taking ``min(len(x), len(y))`` of a 2-D ``y`` is exactly the truncation this
  // replaced -- band 1 followed by the head of band 2, joined into one line.
  const rawCurves = spectrum.curves ?? [];
  const bands = rawCurves
    .map((row) => (row ?? []).map((v) => (Number.isFinite(v) ? v : Number.NaN)))
    .filter((row) => row.length > 1);
  const ysRaw = bands.length
    ? []
    : (spectrum.y ?? []).filter((v) => Number.isFinite(v));
  const n = Math.min(xs.length, ysRaw.length);
  const xsN = xs.slice(0, n);
  const ysN = ysRaw.slice(0, n);
  const width = bands.length ? Math.min(xs.length, ...bands.map((r) => r.length)) : 0;
  const xsB = xs.slice(0, width);
  const bandsN = bands.map((row) => row.slice(0, width));
  const allY = bandsN.length ? bandsN.flat().filter((v) => Number.isFinite(v)) : ysN;
  const xmax = xsN.length ? Math.max(...xsN) : xsB.length ? Math.max(...xsB) : 1;
  const xmin = xsN.length ? Math.min(...xsN) : xsB.length ? Math.min(...xsB) : 0;
  const ymax = allY.length ? Math.max(...allY) : 1;
  // Band structures straddle E_F, so the axis has to include zero or half the
  // plot sits above the frame; a DOS does not, and forcing it there would
  // flatten every peak against the top.
  const ymin = bandsN.length ? Math.min(0, Math.min(...allY)) : 0;
  const padX = (xmax - xmin) * 0.02 || 1;
  return {
    xs: bandsN.length ? xsB : xsN,
    ys: ysN,
    bands: bandsN,
    xmin: Math.max(0, xmin - padX),
    xmax: xmax + padX,
    ymin,
    ymax,
    centroid: (spectrum.peaks?.length ?? 0) > 0 && xsN.length < 2000,
  };
}

/**
 * The spectrum trace.  ``zoom`` and ``pan`` let the lightbox magnify a region
 * without re-deriving the model; the dock passes neither.
 */
export function SpectrumPlot({
  spectrum,
  zoom = 1,
  panX = 0,
  className = "w-full",
}: {
  spectrum: SpectrumLike;
  zoom?: number;
  panX?: number;
  className?: string;
}) {
  const { theme } = useEditor();
  // The SVG carries the *resolved* theme, not the setting: `wb-system` is a
  // menu choice with no token set behind it, and writing it here would produce
  // a `data-theme` value no stylesheet can match -- so an exported plot would
  // silently lose whatever the theme attribute was driving.
  const resolvedTheme = resolveTheme(theme);
  const ms = isMassSpectrum(spectrum);
  const axis = "rgb(var(--c-text-dim))";
  // Monochrome language: the trace is drawn in the primary text colour, so it
  // reads as ink on paper rather than as a coloured highlight.
  const stroke = "rgb(var(--c-text))";

  const model = buildModel(spectrum);
  const view = (() => {
    const spanX = (model.xmax - model.xmin) || 1;
    const spanY = (model.ymax - model.ymin) || 1;
    const cx = model.xmin + spanX / 2 + panX;
    const cy = (model.ymax + model.ymin) / 2;
    const halfW = (spanX / 2) * zoom;
    const halfH = (spanY / 2) * zoom;
    return {
      xmin: Math.max(0, cx - halfW),
      xmax: cx + halfW,
      ymin: cy - halfH,
      ymax: cy + halfH,
    };
  })();

  const px = (v: number) =>
    PLOT_M.left +
    ((v - view.xmin) / (view.xmax - view.xmin || 1)) * (PLOT_W - PLOT_M.left - PLOT_M.right);
  const py = (v: number) =>
    PLOT_H -
    PLOT_M.bottom -
    ((v - view.ymin) / (view.ymax - view.ymin || 1)) * (PLOT_H - PLOT_M.top - PLOT_M.bottom);

  const xTicks = niceTicks(view.xmin, view.xmax);
  const yTicks = niceTicks(view.ymin, view.ymax, 4);

  const paths = (() => {
    if (!model.xs.length) return { sticks: "", profile: "", bands: [] as string[] };
    if (model.bands.length) {
      return {
        sticks: "",
        profile: "",
        bands: model.bands.map((row) => {
          const pts: string[] = [];
          for (let i = 0; i < model.xs.length; i += 1) {
            const v = row[i];
            if (!Number.isFinite(v)) continue;
            const x = px(model.xs[i]);
            if (x < -2 || x > PLOT_W + 2) continue;
            pts.push(`${x.toFixed(1)},${py(v).toFixed(1)}`);
          }
          return pts.length ? `M${pts.join(" L")}` : "";
        }),
      };
    }
    if (model.centroid) {
      let d = "";
      for (let i = 0; i < model.xs.length; i += 1) {
        const x = px(model.xs[i]);
        if (x < -2 || x > PLOT_W + 2) continue;
        d += `M${x.toFixed(1)} ${py(0).toFixed(1)} L${x.toFixed(1)} ${py(model.ys[i]).toFixed(1)} `;
      }
      return { sticks: d.trim(), profile: "", bands: [] as string[] };
    }
    const pts: string[] = [];
    for (let i = 0; i < model.xs.length; i += 1) {
      const x = px(model.xs[i]);
      if (x < -2 || x > PLOT_W + 2) continue;
      pts.push(`${x.toFixed(1)},${py(model.ys[i]).toFixed(1)}`);
    }
    return { sticks: "", profile: pts.length ? `M${pts.join(" L")}` : "", bands: [] as string[] };
  })();


  const xUnit = spectrum.x_unit || (ms ? "m/z" : "");
  const yUnit = spectrum.y_unit || "";

  return (
    <svg
      viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
      className={className}
      role="img"
      data-theme={resolvedTheme}
    >
      {yTicks.map((t) => (
        <g key={`y${t}`}>
          <line
            x1={PLOT_M.left}
            x2={PLOT_W - PLOT_M.right}
            y1={py(t)}
            y2={py(t)}
            stroke={axis}
            strokeOpacity={0.18}
          />
          <text x={PLOT_M.left - 6} y={py(t) + 3} textAnchor="end" fontSize="9" fill={axis}>
            {view.ymax > 1000 ? `${(t / 1000).toFixed(t % 1000 ? 1 : 0)}k` : t.toPrecision(3)}
          </text>
        </g>
      ))}
      {xTicks.map((t) => (
        <g key={`x${t}`}>
          <line x1={px(t)} x2={px(t)} y1={py(model.ymin)} y2={py(model.ymin) - 4} stroke={axis} />
          <text x={px(t)} y={PLOT_H - PLOT_M.bottom + 14} textAnchor="middle" fontSize="9" fill={axis}>
            {Math.abs(t) >= 1000 ? t.toFixed(0) : Number(t.toPrecision(4))}
          </text>
        </g>
      ))}
      {/* The baseline sits at the data's own floor, not at a hard zero: a band
          structure straddles E_F, and pinning the axis line to y=0 would drop
          the lower half of the plot into the frame margin. */}
      <line
        x1={PLOT_M.left}
        x2={PLOT_W - PLOT_M.right}
        y1={py(model.ymin)}
        y2={py(model.ymin)}
        stroke={axis}
      />
      <line
        x1={PLOT_M.left}
        x2={PLOT_M.left}
        y1={PLOT_M.top}
        y2={py(model.ymin)}
        stroke={axis}
      />
      <text x={PLOT_W - PLOT_M.right} y={PLOT_H - 4} textAnchor="end" fontSize="9" fill={axis}>
        {xUnit}
      </text>
      <text x={10} y={PLOT_M.top + 4} fontSize="9" fill={axis}>
        {yUnit}
      </text>

      {/* E_F reference for a band structure: without it "crosses zero" is
          something the reader has to infer from the tick labels. */}
      {model.bands.length > 0 && view.ymin < 0 && view.ymax > 0 && (
        <line
          x1={PLOT_M.left}
          x2={PLOT_W - PLOT_M.right}
          y1={py(0)}
          y2={py(0)}
          stroke={axis}
          strokeDasharray="4 3"
        />
      )}
      {paths.bands.map((d, i) =>
        d ? (
          <path
            key={`band${i}`}
            d={d}
            fill="none"
            stroke={stroke}
            // Thinner per band so a dense structure does not read as a solid
            // block; the opacity keeps four bands separable without colour.
            strokeWidth={model.bands.length > 6 ? 0.8 : 1.1}
            strokeOpacity={model.bands.length > 6 ? 0.75 : 0.9}
          />
        ) : null
      )}
      {paths.profile && <path d={paths.profile} fill="none" stroke={stroke} strokeWidth={1.4} />}
      {paths.sticks && (
        <path d={paths.sticks} fill="none" stroke={stroke} strokeWidth={1.1} strokeLinecap="round" />
      )}

    </svg>
  );
}

/** Full-window enlarged view. */
export default function SpectrumLightbox({
  spectrum,
  title,
  onClose,
}: {
  spectrum: SpectrumLike;
  title: string;
  onClose: () => void;
}) {
  const { lang } = useEditor();
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState(0);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const drag = useRef<{ startX: number; startPan: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const reset = useCallback(() => {
    setZoom(1);
    setPan(0);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "0") reset();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, reset]);

  // Wheel zoom about the cursor, so the point under the pointer stays put.
  function onWheel(event: React.WheelEvent) {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 0.85 : 1.18;
    setZoom((value) => Math.min(40, Math.max(1, value * factor)));
  }

  function onPointerDown(event: React.PointerEvent) {
    drag.current = { startX: event.clientX, startPan: pan };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: React.PointerEvent) {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    if (drag.current) {
      const span = (PLOT_W - PLOT_M.left - PLOT_M.right) / rect.width;
      setPan(drag.current.startPan - (event.clientX - drag.current.startX) * span * zoom);
    }
    // Map the pointer back to data coordinates for the readout.
    const svgX = ((event.clientX - rect.left) / rect.width) * PLOT_W;
    const svgY = ((event.clientY - rect.top) / rect.height) * PLOT_H;
    const model = buildModel(spectrum);
    const spanX = ((model.xmax - model.xmin) || 1) * zoom;
    const centre = model.xmin + ((model.xmax - model.xmin) || 1) / 2 + pan;
    const x = centre - spanX / 2 + ((svgX - PLOT_M.left) / (PLOT_W - PLOT_M.left - PLOT_M.right)) * spanX;
    const ymax = ((model.ymax || 1) * zoom) / 2;
    const y =
      ((PLOT_H - PLOT_M.bottom - svgY) / (PLOT_H - PLOT_M.top - PLOT_M.bottom)) * (ymax * 2);
    if (
      svgX >= PLOT_M.left &&
      svgX <= PLOT_W - PLOT_M.right &&
      svgY >= PLOT_M.top &&
      svgY <= PLOT_H - PLOT_M.bottom
    ) {
      setCursor({ x, y });
    }
  }

  function onPointerUp(event: React.PointerEvent) {
    drag.current = null;
    (event.target as Element).releasePointerCapture?.(event.pointerId);
  }

  const ms = isMassSpectrum(spectrum);

  return (
    <div
      className="fixed inset-0 z-[70] flex flex-col bg-canvas/97 backdrop-blur-sm"
      onClick={onClose}
    >
      <header
        className="flex shrink-0 items-center gap-3 border-b border-line bg-panel px-4 py-2"
        onClick={(event) => event.stopPropagation()}
      >
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[rgb(var(--c-text))]">
          {title}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-[rgb(var(--c-text-faint))]">
          {cursor
            ? `${ms ? "m/z" : spectrum.x_unit || "x"} ${cursor.x.toFixed(4)} · ${
                spectrum.y_unit || "y"
              } ${cursor.y.toPrecision(4)}`
            : lang === "zh"
              ? "滚轮缩放 · 拖动平移 · Esc 关闭"
              : "wheel to zoom · drag to pan · Esc to close"}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setZoom((value) => Math.max(1, value / 1.4))}
            title={lang === "zh" ? "缩小" : "Zoom out"}
            className="flex h-7 w-7 items-center justify-center rounded border border-line text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            <IconMinus size={13} />
          </button>
          <span className="w-12 text-center font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
            {zoom.toFixed(1)}×
          </span>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.min(40, value * 1.4))}
            title={lang === "zh" ? "放大" : "Zoom in"}
            className="flex h-7 w-7 items-center justify-center rounded border border-line text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            <IconPlus size={13} />
          </button>
          <button
            type="button"
            onClick={reset}
            title={lang === "zh" ? "复位" : "Reset"}
            className="rounded border border-line px-2 py-1 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            1:1
          </button>
        </div>
        <button
          type="button"
          onClick={onClose}
          title={translate(lang, "close")}
          className="shrink-0 rounded border border-line px-2.5 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          {translate(lang, "close")}
        </button>
      </header>

      <div
        ref={wrapRef}
        className="min-h-0 flex-1 cursor-grab overflow-hidden p-4 active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          drag.current = null;
          setCursor(null);
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <SpectrumPlot spectrum={spectrum} zoom={zoom} panX={pan} />
      </div>

      <footer
        className="shrink-0 border-t border-line bg-panel px-4 py-1.5 text-[10px] text-[rgb(var(--c-text-faint))]"
        onClick={(event) => event.stopPropagation()}
      >
        {spectrum.name || "—"} · {spectrum.mode || translate(lang, "unlabelled")} ·{" "}
        {(spectrum.x ?? []).length} {lang === "zh" ? "点" : "pts"} ·{" "}
        {(spectrum.peaks ?? []).length} {lang === "zh" ? "峰" : "peaks"}
        {spectrum.precursor_mz ? ` · precursor m/z ${spectrum.precursor_mz}` : ""}
      </footer>
    </div>
  );
}