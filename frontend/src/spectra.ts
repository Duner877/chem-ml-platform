/** Extract serialized Spectrum objects from a run result.
 *
 * The backend serialises every node output port with ``serialize_object``, so
 * Spectrum objects arrive as plain JSON: ``{ type: "Spectrum", x: [...],
 * y: [...], ... }``.  This helper walks the records (including nested lists,
 * because ``multi`` ports carry object lists) and collects every spectrum for
 * the plot panel.
 */

import type { RunResult } from "./types";

export interface SpectrumLike {
  type?: string;
  mode?: string;
  name?: string;
  x?: number[];
  y?: number[];
  x_unit?: string;
  y_unit?: string;
  peaks?: Array<{ x?: number; y?: number }>;
  precursor_mz?: number | null;
  ms_level?: number;
  polarity?: string;
}

export interface PlotSpectrum {
  /** ``nodeLabel / port`` shown in the selector. */
  source: string;
  spectrum: SpectrumLike;
}

function isSpectrum(value: unknown): value is SpectrumLike {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { type?: string }).type === "Spectrum" &&
    Array.isArray((value as { x?: unknown }).x)
  );
}

function walk(value: unknown, sink: SpectrumLike[]): void {
  if (isSpectrum(value)) {
    sink.push(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) walk(item, sink);
    return;
  }
  if (typeof value === "object" && value !== null) {
    // Inspect dict values too (e.g. {"spectrum": {...}}) but never recurse
    // into huge numeric arrays.
    for (const item of Object.values(value as Record<string, unknown>)) {
      if (Array.isArray(item)) {
        if (item.length && item.every((v) => typeof v === "number")) continue;
        walk(item, sink);
      } else if (typeof item === "object" && item !== null) {
        walk(item, sink);
      }
    }
  }
}

/** Collect every spectrum produced by the last run, in node execution order. */
export function extractSpectra(result: RunResult | null): PlotSpectrum[] {
  if (!result?.records) return [];
  const found: PlotSpectrum[] = [];
  for (const [nodeId, record] of Object.entries(result.records)) {
    const outputs = record.outputs;
    if (!outputs || typeof outputs !== "object") continue;
    const label = record.node_type || nodeId;
    for (const [port, value] of Object.entries(outputs)) {
      const spectra: SpectrumLike[] = [];
      walk(value, spectra);
      for (const spectrum of spectra) {
        found.push({ source: `${label} · ${port}`, spectrum });
      }
    }
  }
  return found;
}

/** Is this an MS spectrum (m/z axis)?  Drives the axis label and stick style. */
export function isMassSpectrum(spectrum: SpectrumLike): boolean {
  const unit = (spectrum.x_unit || "").toLowerCase();
  const mode = (spectrum.mode || "").toUpperCase();
  return unit.includes("m/z") || mode === "MS" || mode === "EI-MS";
}
