/** Click-to-browse file picking for ``file`` typed node parameters.
 *
 * A node parameter of type ``file`` is a plain path string, and typing a
 * Windows path by hand is unpleasant enough that people simply never load
 * their own measurement.  This module gives the editor two ways to fill it in:
 *
 * 1. **Desktop build (Electron)** -- the preload bridge exposes
 *    ``pickFile()``, which opens the *native* Windows/macOS/Linux dialog in the
 *    main process and returns the absolute path. This is the primary path: it
 *    is the only one that yields a path the backend (which runs on the same
 *    machine, in a different process) can actually open.
 *
 * 2. **Browser build (``start-platform.bat``)** -- there is no native dialog
 *    and a browser ``<input type=file>`` deliberately hides the path, so the
 *    picker falls back to the backend's own filesystem browser
 *    (``GET /api/files/browse``).  The backend runs locally and reads the
 *    directories it lists, so this stays a local operation.
 *
 * Both paths return an **absolute path**.  Every importer node
 * (``SpectrumFileNode`` / ``TableFileNode`` / ``ImageFileNode`` /
 * ``VendorSpectrumNode``) tries ``Path(raw)`` first and only falls back to
 * "relative to the repository root", so an absolute path works unchanged.
 */

import { api } from "./api";

/** The subset of the preload bridge this module needs. */
interface DesktopFileBridge {
  pickFile?: (options?: {
    title?: string;
    filters?: Array<{ name: string; extensions: string[] }>;
    defaultPath?: string;
  }) => Promise<{ canceled: boolean; path: string; name: string } | null>;
}

const bridge = (globalThis as { chemmlDesktop?: DesktopFileBridge }).chemmlDesktop;

/** True when the native dialog is available (packaged / dev desktop shell). */
export function canUseNativePicker(): boolean {
  return typeof bridge?.pickFile === "function";
}

export interface PickedFile {
  /** Absolute path on the machine running the backend. */
  path: string;
  /** File name (for the chip label). */
  name: string;
  /** Byte size when known, else ``undefined``. */
  size?: number;
}

/** Filter presets per parameter description, matched case-insensitively. */
const FILTER_PRESETS: Array<{ test: RegExp; filters: Array<{ name: string; extensions: string[] }> }> = [
  {
    test: /质谱|谱图|spectrum|mass spec|mzml|spectr/i,
    filters: [
      { name: "Mass spectrometry", extensions: ["mzml", "mzxml", "mgf", "msp", "xy", "raw", "d"] },
      { name: "All files", extensions: ["*"] },
    ],
  },
  {
    test: /表格|csv|tsv|table/i,
    filters: [
      { name: "Tables", extensions: ["csv", "tsv", "txt"] },
      { name: "All files", extensions: ["*"] },
    ],
  },
  {
    test: /图像|图片|image|png|tiff|显微/i,
    filters: [
      { name: "Images", extensions: ["png", "jpg", "jpeg", "tif", "tiff", "bmp"] },
      { name: "All files", extensions: ["*"] },
    ],
  },
  {
    test: /结构|structure|sdf|mol|cif|xyz/i,
    filters: [
      { name: "Structures", extensions: ["sdf", "mol", "mol2", "smi", "smiles", "cif", "xyz", "vasp"] },
      { name: "All files", extensions: ["*"] },
    ],
  },
];

/** Best filter preset for a parameter description (defaults to "all files"). */
export function filtersFor(description: string) {
  for (const preset of FILTER_PRESETS) {
    if (preset.test.test(description)) return preset.filters;
  }
  return [{ name: "All files", extensions: ["*"] }];
}

/**
 * Open a picker and return the chosen file, or ``null`` when the user
 * cancelled.  Never throws for a user cancel; a genuine failure is surfaced as
 * an error message so the caller can show it instead of silently doing nothing.
 */
export async function pickLocalFile(
  description: string,
  startPath?: string
): Promise<PickedFile | null> {
  if (canUseNativePicker()) {
    const result = await bridge!.pickFile!({
      title: description || "选择文件 / Choose a file",
      filters: filtersFor(description),
      defaultPath: startPath || undefined,
    });
    if (!result || result.canceled || !result.path) return null;
    return { path: result.path, name: result.name || basename(result.path) };
  }
  return pickViaBackend(startPath);
}

/** Browser-mode fallback: ask the backend which files live in a directory. */
async function pickViaBackend(startPath?: string): Promise<PickedFile | null> {
  const listing = await api.browseFiles(startPath ?? "");
  // One directory with exactly one file: take it without a second click.
  if (listing.files.length === 1 && listing.directories.length === 0) {
    const only = listing.files[0];
    return {
      path: only.path,
      name: only.name,
      ...(typeof only.size === "number" ? { size: only.size } : {}),
    };
  }
  // Otherwise the caller renders the listing; signal "no single pick".
  return null;
}

/** Directory entry used by the in-app browser fallback. */
export interface BrowseEntry {
  name: string;
  path: string;
  size?: number;
}

/** Open the in-app filesystem browser at ``startPath`` (browser mode only). */
export async function browseFiles(startPath = "") {
  return api.browseFiles(startPath);
}

function basename(value: string): string {
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] || value;
}

/** File name of a path (posix or Windows separators). */
export { basename as fileNameOf };