/** Click-to-browse widget for ``file`` typed node parameters (v0.7.2).
 *
 * Replaces the bare path text box.  A path is hard to type and impossible to
 * get right on Windows, so the box is now a *button*: click it, pick the file,
 * and the absolute path lands in the parameter.
 *
 * Two pickers, chosen automatically (see :mod:`../filePicker`):
 * * desktop build -> the native OS dialog raised by the Electron main process;
 * * browser build -> an in-app browser backed by ``GET /api/files/browse``.
 *
 * Typing is still possible: the path stays an editable text field, so a
 * workflow that references a repo-relative dataset keeps working unchanged.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { pickLocalFile, canUseNativePicker } from "../filePicker";
import { translate } from "../i18n";
import { useEditor } from "../store";
import type { FileEntry, FileListing } from "../types";
import { IconFolder, IconFile } from "../components/Icons";

function basename(value: string): string {
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] || value;
}

/** In-app filesystem browser (browser mode fallback). */
function BrowseDialog({
  startPath,
  onPick,
  onClose,
}: {
  startPath: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const { lang } = useEditor();
  const [listing, setListing] = useState<FileListing | null>(null);
  const [error, setError] = useState("");
  const [manual, setManual] = useState(startPath);

  const load = useCallback(async (path: string) => {
    setError("");
    try {
      const payload = await api.browseFiles(path);
      setListing(payload);
      setManual(payload.path);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load(startPath);
  }, [load, startPath]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const entry = (item: FileEntry, isDir: boolean) => (
    <button
      key={item.path}
      type="button"
      onClick={() => (isDir ? void load(item.path) : onPick(item.path))}
      className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[11px] transition hover:bg-panel2 ${
        isDir
          ? "text-[rgb(var(--c-text))]"
          : item.readable === false
            ? "text-[rgb(var(--c-text-faint))]"
            : "text-[rgb(var(--c-text-dim))]"
      }`}
    >
      {isDir ? <IconFolder size={12} /> : <IconFile size={12} />}
      <span className="truncate">{item.name}</span>
      {!isDir && typeof item.size === "number" && (
        <span className="ml-auto shrink-0 font-mono text-[9px] text-[rgb(var(--c-text-faint))]">
          {item.size < 1024
            ? `${item.size} B`
            : item.size < 1024 * 1024
              ? `${(item.size / 1024).toFixed(0)} KB`
              : `${(item.size / 1024 / 1024).toFixed(1)} MB`}
        </span>
      )}
    </button>
  );

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-6"
      onClick={onClose}
    >
      <div
        className="cml-menu flex max-h-[70vh] w-[560px] max-w-full flex-col overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center gap-2 border-b border-line px-3 py-2">
          <IconFolder size={13} />
          <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-[rgb(var(--c-text-dim))]">
            {listing?.path ?? (error ? "—" : "…")}
          </span>
          {listing?.parent && (
            <button
              type="button"
              onClick={() => void load(listing.parent)}
              className="shrink-0 rounded border border-line px-2 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
            >
              {lang === "zh" ? "上级" : "Up"}
            </button>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {error && (
            <p className="px-2 py-2 text-[11px] text-bad">{error}</p>
          )}
          {!error && !listing && (
            <p className="px-2 py-2 text-[11px] text-[rgb(var(--c-text-faint))]">
              {lang === "zh" ? "读取中…" : "loading…"}
            </p>
          )}
          {listing?.directories.map((item) => entry(item, true))}
          {listing?.files.map((item) => entry(item, false))}
          {listing && listing.directories.length === 0 && listing.files.length === 0 && (
            <p className="px-2 py-3 text-[11px] text-[rgb(var(--c-text-faint))]">
              {lang === "zh" ? "此目录为空" : "this directory is empty"}
            </p>
          )}
          {listing?.truncated && (
            <p className="px-2 py-1 text-[10px] text-[rgb(var(--c-text-faint))]">
              {lang === "zh" ? "条目过多，仅显示前 500 项" : "too many entries — showing the first 500"}
            </p>
          )}
        </div>

        <footer className="flex items-center gap-2 border-t border-line px-3 py-2">
          <input
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            placeholder={lang === "zh" ? "或直接输入路径" : "or type a path"}
            className="cml-widget font-mono"
          />
          <button
            type="button"
            onClick={() => manual.trim() && onPick(manual.trim())}
            className="shrink-0 rounded border border-line px-2 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            {translate(lang, "fileUsePath")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded border border-line px-2 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
          >
            {translate(lang, "cancel")}
          </button>
        </footer>
      </div>
    </div>
  );
}

/**
 * A path input with a Browse button.  ``onChange`` receives the new path.
 * ``compact`` renders the node-card variant (icon only, no status line).
 */
export default function FilePickerField({
  value,
  description,
  onChange,
  compact = false,
}: {
  value: unknown;
  description: string;
  onChange: (path: string) => void;
  compact?: boolean;
}) {
  const { lang, pushLog } = useEditor();
  const path = String(value ?? "");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [status, setStatus] = useState<"unknown" | "ok" | "missing">("unknown");
  const inputRef = useRef<HTMLInputElement>(null);

  // Probe the path so a wrong one is reported *before* the run, not after.
  useEffect(() => {
    let cancelled = false;
    const text = path.trim();
    if (!text) {
      setStatus("unknown");
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .probeFile(text)
        .then((probe) => {
          if (!cancelled) setStatus(probe.exists && !probe.is_dir ? "ok" : "missing");
        })
        .catch(() => {
          if (!cancelled) setStatus("unknown");
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [path]);

  async function browse() {
    if (canUseNativePicker()) {
      try {
        const picked = await pickLocalFile(description, path || undefined);
        if (picked) {
          onChange(picked.path);
          pushLog(`$ ${lang === "zh" ? "已选择文件" : "picked file"}: ${picked.name}`);
        }
      } catch (error) {
        pushLog(`! ${(error as Error).message}`);
      }
      return;
    }
    setDialogOpen(true);
  }

  return (
    <>
      <div className="flex items-center gap-1">
        <input
          ref={inputRef}
          type="text"
          value={path}
          placeholder={lang === "zh" ? "选择或输入文件路径" : "pick or type a file path"}
          title={path || undefined}
          onChange={(event) => onChange(event.target.value)}
          className={`cml-widget font-mono ${compact ? "text-[10px]" : ""}`}
        />
        <button
          type="button"
          onClick={() => void browse()}
          title={translate(lang, "fileBrowse")}
          className="flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-1 text-[10px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          <IconFolder size={12} />
          {compact ? "" : translate(lang, "fileBrowse")}
        </button>
      </div>
      {!compact && status !== "unknown" && (
        <p
          className={`mt-0.5 text-[9px] ${
            status === "ok"
              ? "text-[rgb(var(--c-text-faint))]"
              : "text-bad"
          }`}
        >
          {status === "ok"
            ? path
            : `${translate(lang, "fileMissing")}: ${basename(path)}`}
        </p>
      )}
      {dialogOpen && (
        <BrowseDialog
          startPath={path}
          onPick={(chosen) => {
            onChange(chosen);
            setDialogOpen(false);
          }}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </>
  );
}