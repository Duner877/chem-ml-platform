/** About dialog — version, codename and a one-paragraph product summary. */

import { useEditor } from "../store";
import { translate } from "../i18n";
import { IconCube } from "./Icons";

export default function AboutDialog() {
  const { lang, aboutOpen, setAboutOpen } = useEditor();
  if (!aboutOpen) return null;

  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/50 p-6">
      <div className="cml-menu w-full max-w-md p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-onAccent">
            <IconCube size={18} />
          </span>
          <div>
            <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">
              Chem ML Platform v{__CHEMML_VERSION__}
            </h2>
            <p className="text-[11px] text-[rgb(var(--c-text-faint))]">
              Trusted Delivery Release
            </p>
          </div>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-[rgb(var(--c-text-dim))]">
          {translate(lang, "aboutBody")}
        </p>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={() => setAboutOpen(false)}
            className="rounded-md bg-accent px-4 py-1.5 text-xs font-semibold text-onAccent transition hover:bg-accent/85"
          >
            {translate(lang, "aboutOk")}
          </button>
        </div>
      </div>
    </div>
  );
}
