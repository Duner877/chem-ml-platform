/** Update badge for the top bar (v0.7.4).
 *
 * A single quiet control that answers "is there a newer release?" without
 * getting in the way.  Three rules:
 *
 *  1. **Silent unless it matters.**  The check runs once at start-up; the
 *     button only changes colour when a newer version exists.  A dialog on
 *     every launch teaches people to dismiss it, and then nobody reads the
 *     release notes.
 *  2. **A failed check is not a green light.**  The badge stays neutral when
 *     the check could not be completed, because "could not reach the server"
 *     and "you are up to date" are different facts.
 *  3. **Clicking always opens the panel**, whatever the state.  The panel is
 *     where the check can be repeated and the download started.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import { IconRefresh } from "./Icons";

export default function UpdateBadge() {
  const { lang, setDockTab } = useEditor();
  const [available, setAvailable] = useState(false);
  const [latest, setLatest] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .updateCheck()
      .then((result) => {
        if (cancelled) return;
        // A failed check leaves the badge neutral: the absence of a network
        // is not evidence that the installation is current.
        if (result.check_failed) return;
        setAvailable(result.update_available);
        setLatest(result.latest_version ?? "");
      })
      .catch(() => {
        /* offline or backend not up yet -- stay neutral */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const open = () => {
    setDockTab("update");
    useEditor.getState().setDockOpen(true);
  };

  const title = available
    ? `${translate(lang, "updateLatest")} ${latest}`
    : translate(lang, "updateCheck");

  return (
    <button
      type="button"
      onClick={open}
      title={title}
      className={`flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] transition ${
        available
          ? "border-good/60 bg-good/15 text-good hover:bg-good/25"
          : "border-line text-[rgb(var(--c-text-dim))] hover:border-accent hover:text-accent"
      }`}
    >
      <IconRefresh size={13} />
      {available ? latest : translate(lang, "updateCheck")}
    </button>
  );
}
