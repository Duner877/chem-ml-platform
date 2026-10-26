/** Software update entry point (v0.7.4).
 *
 * The one place in the GUI where the user finds out whether a newer release
 * exists, and where they start the update.  Four rules shape it:
 *
 *  1. **"Cannot check" is not "up to date".**  The backend answers with a
 *     `check_failed` flag precisely because a network failure must never be
 *     dressed up as a clean bill of health.  The panel shows the three
 *     outcomes apart: up to date, update available, check failed.
 *  2. **The current version is shown before anything else.**  A user who
 *     cannot check still deserves to know what they are running.
 *  3. **The update is the user's decision.**  The panel never starts an
 *     install on its own; it downloads on request and hands the file to the
 *     installer only after the download completed and was checksummed.
 *  4. **A silent failure is a lie.**  If the download or the hand-off
 *     fails, the panel says so in words -- a spinner that stops without a
 *     message reads as success.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { UpdateCheck, UpdateDownload } from "../types";

/** Which action is in flight, so one button's spinner is honest. */
type Pending = "" | "check" | "download" | "install";

/**
 * The Electron bridge the desktop shell exposes.
 *
 * In a browser (the dev flow) it is absent, and the panel must still work:
 * it then says the automatic install is unavailable and offers the release
 * page instead.  Silently doing nothing would be the worst outcome, so the
 * bridge's absence is a *state the panel renders*, not an error it swallows.
 */
interface UpdateBridge {
  /** Launch the downloaded installer. Resolves with the launch outcome. */
  installUpdate?: (filePath: string) => Promise<{ ok: boolean; message?: string }>;
  /** Open a URL in the user's browser. */
  openExternal?: (url: string) => Promise<unknown>;
  /** Whether the desktop shell is present at all. */
  isDesktop?: boolean;
}

function bridge(): UpdateBridge {
  return (
    (globalThis as { chemmlDesktop?: UpdateBridge }).chemmlDesktop ?? {}
  );
}

/** Human-readable size for the download progress line. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UpdatePanel() {
  const { lang, pushLog } = useEditor();
  const [info, setInfo] = useState<UpdateCheck | null>(null);
  const [download, setDownload] = useState<UpdateDownload | null>(null);
  const [pending, setPending] = useState<Pending>("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const shell = bridge();

  /** Ask GitHub whether a newer release exists. */
  const check = useCallback(async () => {
    setPending("check");
    setError("");
    setNotice("");
    try {
      const result = await api.updateCheck();
      setInfo(result);
      if (result.check_failed) {
        setError(result.message || translate(lang, "updateCheckFailed"));
      }
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setError(`${translate(lang, "updateCheckFailed")}：${message}`);
      pushLog(`[update] check failed: ${message}`);
    } finally {
      setPending("");
    }
  }, [lang, pushLog]);

  // Check once when the panel opens.  A version check that only runs when
  // the user presses a button is a feature nobody uses.
  useEffect(() => {
    void check();
  }, [check]);

  /** Download the installer into the local update cache. */
  const runDownload = useCallback(async () => {
    if (!info?.download_url) {
      setError(translate(lang, "updateNoInstaller"));
      return;
    }
    setPending("download");
    setError("");
    setNotice("");
    setDownload(null);
    try {
      const result = await api.updateDownload(info.download_url);
      setDownload(result);
      setNotice(
        `${translate(lang, "updateDownloaded")}（${formatSize(result.size_bytes)}）`
      );
      pushLog(
        `[update] downloaded ${result.path} sha256=${result.sha256.slice(0, 12)}`
      );
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setError(`${translate(lang, "updateDownloadFailed")}：${message}`);
      pushLog(`[update] download failed: ${message}`);
    } finally {
      setPending("");
    }
  }, [info, lang, pushLog]);

  /** Hand the downloaded file to the installer. */
  const runInstall = useCallback(async () => {
    if (!download) return;
    if (!shell.installUpdate) {
      setError(translate(lang, "updateNoInstallerRunner"));
      return;
    }
    setPending("install");
    setError("");
    try {
      const outcome = await shell.installUpdate(download.path);
      if (outcome?.ok) {
        setNotice(translate(lang, "updateInstallStarted"));
      } else {
        setError(
          outcome?.message || translate(lang, "updateInstallFailed")
        );
      }
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setError(`${translate(lang, "updateInstallFailed")}：${message}`);
      pushLog(`[update] install failed: ${message}`);
    } finally {
      setPending("");
    }
  }, [download, lang, pushLog, shell]);

  /** Open the release page in the system browser. */
  const openRelease = useCallback(async () => {
    const url = info?.release_url;
    if (!url) return;
    if (shell.openExternal) {
      await shell.openExternal(url);
      return;
    }
    window.open(url, "_blank", "noopener");
  }, [info, shell]);

  const current = info?.current_version ?? "—";
  const latest = info?.latest_version ?? "—";

  return (
    <section className="flex h-full flex-col gap-3 overflow-y-auto p-3 text-[11px]">
      <header className="flex flex-col gap-1">
        <h2 className="text-[12px] font-semibold text-[rgb(var(--c-text))]">
          {translate(lang, "updateTitle")}
        </h2>
        <p className="text-[rgb(var(--c-text-dim))]">
          {translate(lang, "updateCurrent")}：{current}
        </p>
      </header>

      {info && !info.check_failed && (
        <div
          className={`rounded border px-2 py-1.5 ${
            info.update_available
              ? "border-warn/40 bg-warn/10 text-warn"
              : "border-good/40 bg-good/10 text-good"
          }`}
        >
          {info.message}
        </div>
      )}

      {error && (
        <div className="rounded border border-bad/40 bg-bad/10 px-2 py-1.5 text-bad">
          {error}
        </div>
      )}

      {notice && (
        <div className="rounded border border-line bg-panel-2 px-2 py-1.5 text-[rgb(var(--c-text))]">
          {notice}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void check()}
          disabled={pending !== ""}
          className="rounded border border-line px-2 py-1 transition hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {pending === "check"
            ? translate(lang, "updateChecking")
            : translate(lang, "updateCheck")}
        </button>

        {info?.release_url && (
          <button
            type="button"
            onClick={() => void openRelease()}
            className="rounded border border-line px-2 py-1 transition hover:border-accent hover:text-accent"
          >
            {translate(lang, "updateReleasePage")}
          </button>
        )}
      </div>

      {info?.update_available && (
        <div className="flex flex-col gap-2 rounded border border-line p-2">
          <div className="flex items-baseline justify-between">
            <span className="text-[rgb(var(--c-text-dim))]">
              {translate(lang, "updateLatest")}
            </span>
            <span className="font-semibold text-accent">{latest}</span>
          </div>

          {info.published_at && (
            <div className="flex items-baseline justify-between">
              <span className="text-[rgb(var(--c-text-dim))]">
                {translate(lang, "updatePublished")}
              </span>
              <span>{info.published_at.slice(0, 10)}</span>
            </div>
          )}

          {info.notes && (
            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded bg-panel-2 p-2 text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
              {info.notes}
            </pre>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void runDownload()}
              disabled={pending !== "" || !info.download_url}
              className="rounded border border-line px-2 py-1 transition hover:border-accent hover:text-accent disabled:opacity-50"
            >
              {pending === "download"
                ? translate(lang, "updateDownloading")
                : translate(lang, "updateDownload")}
            </button>

            <button
              type="button"
              onClick={() => void runInstall()}
              disabled={pending !== "" || !download}
              className="rounded border border-accent px-2 py-1 text-accent transition hover:bg-accent/10 disabled:opacity-50"
            >
              {pending === "install"
                ? translate(lang, "updateInstalling")
                : translate(lang, "updateInstall")}
            </button>
          </div>

          {!info.download_url && (
            <p className="text-warn">{translate(lang, "updateNoInstaller")}</p>
          )}

          {download && (
            <p className="break-all text-[10px] text-[rgb(var(--c-text-dim))]">
              {download.path}
              <br />
              SHA-256：{download.sha256.slice(0, 24)}…
            </p>
          )}
        </div>
      )}

      {!info && pending === "check" && (
        <p className="text-[rgb(var(--c-text-dim))]">
          {translate(lang, "updateChecking")}
        </p>
      )}
    </section>
  );
}
