/** Floating overlay drawer used by the node library, the workflow list and the
 *  console (the ComfyUI left / bottom panels are overlays, not columns). */

import type { ReactNode } from "react";

interface DrawerProps {
  title: string;
  subtitle?: string;
  side: "left" | "bottom";
  width?: string;
  height?: string;
  onClose: () => void;
  children: ReactNode;
}

export default function Drawer({
  title,
  subtitle,
  side,
  width = "w-80",
  height = "h-64",
  onClose,
  children,
}: DrawerProps) {
  const position =
    side === "left"
      ? `absolute bottom-3 left-14 top-3 z-20 flex ${width} flex-col`
      : `absolute inset-x-14 bottom-14 z-20 flex ${height} flex-col`;

  return (
    <section className={`${position} cml-menu overflow-hidden`}>
      <header className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2">
        <h2 className="text-xs font-semibold text-[rgb(var(--c-text))]">{title}</h2>
        {subtitle && (
          <span className="text-[10px] text-[rgb(var(--c-text-faint))]">{subtitle}</span>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={onClose}
          title="close"
          className="rounded px-1.5 py-0.5 text-[11px] text-[rgb(var(--c-text-dim))] transition hover:bg-panel2 hover:text-[rgb(var(--c-text))]"
        >
          ✕
        </button>
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}
