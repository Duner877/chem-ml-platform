/** Top menu bar — the ComfyUI-style application header.
 *
 * Layout (left → right): brand + version, the Workflow / Edit / Help menus,
 * the current workflow name chip, then the Manager / artefacts / theme /
 * language / backend controls.
 */

import { useEffect, useRef, useState } from "react";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { useRunActions } from "../workflowActions";
import { api } from "../api";
import type { WorkflowSummary } from "../types";
import { THEME_IDS, type ThemeId } from "../theme";
import {
  IconChevron,
  IconCube,
  IconGlobe,
  IconImage,
  IconPalette,
  IconStar,
  IconCheck,
} from "./Icons";

/** Minimal shape of the Electron preload bridge (absent in browser mode). */
interface DesktopBridge {
  windowControl: (action: "minimize" | "maximize" | "close") => void;
}

const desktopApi = (globalThis as { chemmlDesktop?: DesktopBridge }).chemmlDesktop;
const isDesktop = Boolean(desktopApi);

function Menu({
  label,
  items,
}: {
  label: string;
  items: Array<{ label: string; onSelect: () => void; danger?: boolean }>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs transition ${
          open
            ? "bg-panel2 text-[rgb(var(--c-text))]"
            : "text-[rgb(var(--c-text-dim))] hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        }`}
      >
        {label}
        <IconChevron size={12} className={open ? "rotate-180" : ""} />
      </button>
      {open && (
        <div className="cml-menu absolute left-0 top-full z-50 mt-1 min-w-44 py-1">
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`flex w-full items-center px-3 py-1.5 text-left text-xs transition hover:bg-panel2 ${
                item.danger
                  ? "text-bad"
                  : "text-[rgb(var(--c-text-dim))] hover:text-[rgb(var(--c-text))]"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TopBar() {
  const {
    lang,
    toggleLang,
    theme,
    cycleTheme,
    nodes,
    edges,
    selectedId,
    backend,
    loadWorkflow,
    clearCanvas,
    duplicateNode,
    removeNode,
    setMarketplace,
    setAboutOpen,
    pushLog,
    setConsoleOpen,
  } = useEditor();
  const { handleRun, handleValidate, buildPayload } = useRunActions();
  const [demos, setDemos] = useState<WorkflowSummary[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .workflows()
      .then(setDemos)
      .catch(() => setDemos([]));
  }, []);

  const themeLabel = (id: ThemeId) =>
    id === "wb-light" ? translate(lang, "themeWbLight") : translate(lang, "themeWbDark");

  async function saveWorkflow() {
    const payload = buildPayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "workflow-chemml.json";
    anchor.click();
    URL.revokeObjectURL(url);
    pushLog("$ workflow saved as workflow-chemml.json");
  }

  function openFile() {
    fileRef.current?.click();
  }

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      loadWorkflow(JSON.parse(text) as { nodes?: unknown[]; edges?: unknown[] });
      pushLog(`$ loaded ${file.name}`);
    } catch (error) {
      pushLog(`! ${(error as Error).message}`);
    } finally {
      event.target.value = "";
    }
  }

  return (
    <header className="cml-titlebar flex h-9 shrink-0 items-center gap-1 border-b border-line bg-panel px-2 text-xs">
      {/* brand ----------------------------------------------------------- */}
      <div className="flex items-center gap-2 px-1">
        <span className="flex h-6 w-6 items-center justify-center rounded bg-accent text-onAccent">
          <IconCube size={14} />
        </span>
        <span className="font-semibold text-[rgb(var(--c-text))]">
          Chem ML Platform
        </span>
        <span className="rounded bg-panel2 px-1.5 py-0.5 text-[10px] text-[rgb(var(--c-text-dim))]">
          v{__CHEMML_VERSION__}
        </span>
      </div>

      <div className="mx-1 h-5 w-px bg-line" />

      {/* menus ----------------------------------------------------------- */}
      <Menu
        label={translate(lang, "menuWorkflow")}
        items={[
          {
            label: translate(lang, "menuNew"),
            onSelect: () => {
              clearCanvas();
              pushLog("$ new workflow");
            },
          },
          { label: translate(lang, "menuSave"), onSelect: saveWorkflow },
          { label: translate(lang, "menuLoad"), onSelect: openFile },
          ...demos.map((demo) => ({
            label: `↳ ${demo.name}`,
            onSelect: () => {
              api
                .workflow(demo.file)
                .then((payload) => {
                  loadWorkflow(payload as { nodes?: unknown[]; edges?: unknown[] });
                  pushLog(`$ loaded ${demo.file}`);
                })
                .catch((error) => pushLog(`! ${(error as Error).message}`));
            },
          })),
        ]}
      />
      <Menu
        label={translate(lang, "menuEdit")}
        items={[
          {
            label: translate(lang, "menuRun"),
            onSelect: () => void handleRun(),
          },
          { label: translate(lang, "menuValidate"), onSelect: () => void handleValidate() },
          {
            label: translate(lang, "menuZoomFit"),
            onSelect: () => window.dispatchEvent(new CustomEvent("chemml:zoom-fit")),
          },
          {
            label: translate(lang, "menuDuplicate"),
            onSelect: () => selectedId && duplicateNode(selectedId),
          },
          {
            label: translate(lang, "menuDelete"),
            danger: true,
            onSelect: () => selectedId && removeNode(selectedId),
          },
          {
            label: translate(lang, "menuClear"),
            danger: true,
            onSelect: () => {
              clearCanvas();
              pushLog("$ clear canvas");
            },
          },
        ]}
      />
      <Menu
        label={translate(lang, "menuHelp")}
        items={[
          { label: translate(lang, "menuManager"), onSelect: () => setMarketplace(true) },
          { label: translate(lang, "menuDocs"), onSelect: () => setAboutOpen(true) },
          { label: translate(lang, "menuAbout"), onSelect: () => setAboutOpen(true) },
        ]}
      />

      {/* workflow name chip --------------------------------------------- */}
      <div className="mx-2 flex min-w-0 items-center gap-2 rounded border border-line bg-canvas px-2 py-1">
        <span className="text-[rgb(var(--c-text-dim))]">
          {translate(lang, "workflowLabel")}
        </span>
        <span className="max-w-56 truncate font-mono text-[11px] text-[rgb(var(--c-text))]">
          workflow-{nodes.length > 0 ? `${nodes.length}n-${edges.length}e` : "untitled"}
          .json
        </span>
      </div>

      <div className="flex-1" />

      {/* right controls --------------------------------------------------- */}
      <button
        type="button"
        onClick={() => setMarketplace(true)}
        className="flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
      >
        <IconStar size={13} />
        {translate(lang, "manager")}
      </button>

      <button
        type="button"
        onClick={() => setConsoleOpen(true)}
        title={translate(lang, "artefacts")}
        className="flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
      >
        <IconImage size={13} />
        {translate(lang, "artefacts")}
      </button>

      {/* theme switcher --------------------------------------------------- */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen((value) => !value)}
          title={translate(lang, "theme")}
          className="flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
        >
          <IconPalette size={13} />
          <span className="hidden sm:inline">{themeLabel(theme)}</span>
          <IconChevron size={11} />
        </button>
        {menuOpen && (
          <div className="cml-menu absolute right-0 top-full z-50 mt-1 w-40 py-1">
            {THEME_IDS.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  useEditor.getState().setTheme(id);
                  setMenuOpen(false);
                }}
                className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-xs transition hover:bg-panel2 ${
                  id === theme
                    ? "text-accent"
                    : "text-[rgb(var(--c-text-dim))] hover:text-[rgb(var(--c-text))]"
                }`}
              >
                {themeLabel(id)}
                {id === theme && <IconCheck size={12} />}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                cycleTheme();
                setMenuOpen(false);
              }}
              className="w-full border-t border-line px-3 py-1.5 text-left text-[11px] text-[rgb(var(--c-text-faint))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
            >
              {translate(lang, "theme")} ⟳
            </button>
          </div>
        )}
      </div>

      {/* language --------------------------------------------------------- */}
      <button
        type="button"
        onClick={toggleLang}
        title={translate(lang, "language")}
        className="flex items-center gap-1.5 rounded border border-line px-2.5 py-1 text-[11px] font-medium text-[rgb(var(--c-text-dim))] transition hover:border-accent hover:text-[rgb(var(--c-text))]"
      >
        <IconGlobe size={13} />
        {lang === "zh" ? "中 / EN" : "EN / 中"}
      </button>

      {/* backend status ---------------------------------------------------- */}
      <span
        className={`ml-1 flex items-center gap-1.5 rounded px-2 py-1 text-[10px] ${
          backend === "online"
            ? "bg-good/15 text-good"
            : backend === "offline"
              ? "bg-bad/15 text-bad"
              : "bg-panel2 text-[rgb(var(--c-text-dim))]"
        }`}
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            backend === "online"
              ? "bg-good"
              : backend === "offline"
                ? "bg-bad"
                : "bg-[rgb(var(--c-text-faint))]"
          }`}
        />
        {backend === "online"
          ? translate(lang, "ready")
          : backend === "offline"
            ? translate(lang, "offline")
            : translate(lang, "connecting")}
      </span>

      {/* window controls (desktop shell only) -------------------------------
       * The native Electron menu bar was removed: this top bar *is* the window
       * chrome now -- it drags the window and hosts the min/max/close buttons,
       * themed exactly like the rest of the UI. */}
      {isDesktop && (
        <div className="ml-1 flex items-center gap-0.5">
          <button
            type="button"
            title={lang === "zh" ? "最小化" : "Minimize"}
            onClick={() => desktopApi?.windowControl("minimize")}
            className="flex h-7 w-8 items-center justify-center rounded text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <rect x="1" y="4.5" width="8" height="1" fill="currentColor" />
            </svg>
          </button>
          <button
            type="button"
            title={lang === "zh" ? "最大化 / 还原" : "Maximize / restore"}
            onClick={() => desktopApi?.windowControl("maximize")}
            className="flex h-7 w-8 items-center justify-center rounded text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <rect
                x="1.5"
                y="1.5"
                width="7"
                height="7"
                fill="none"
                stroke="currentColor"
                strokeWidth="1"
              />
            </svg>
          </button>
          <button
            type="button"
            title={lang === "zh" ? "关闭" : "Close"}
            onClick={() => desktopApi?.windowControl("close")}
            className="flex h-7 w-8 items-center justify-center rounded text-[rgb(var(--c-text-dim))] transition hover:bg-bad hover:text-white"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <path
                d="M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5"
                stroke="currentColor"
                strokeWidth="1.1"
              />
            </svg>
          </button>
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={onFile}
      />
    </header>
  );
}
