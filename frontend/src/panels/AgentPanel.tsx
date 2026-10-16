/** Agent panel: ask a scientific question, review the plan and the conclusion. */

import { useState } from "react";
import { api } from "../api";
import { useEditor } from "../store";
import { translate } from "../i18n";
import type { AgentAnswer } from "../types";

const STATUS_COLOR: Record<string, string> = {
  completed: "text-good",
  failed: "text-bad",
  running: "text-accent",
  skipped: "text-[rgb(var(--c-text-faint))]",
};

export default function AgentPanel() {
  const { lang, pushLog, credentialCount, setDockTab, setDockOpen } = useEditor();
  const [question, setQuestion] = useState(() =>
    lang === "zh"
      ? "请分析这个未知化合物 C8H10N4O2"
      : "Please analyse this unknown compound C8H10N4O2"
  );
  const [useLlm, setUseLlm] = useState(true);
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState<"" | "ask" | "plan">("");
  const [error, setError] = useState("");

  async function ask() {
    if (!question.trim()) return;
    setBusy("ask");
    setError("");
    try {
      const result = await api.agentAsk(question, useLlm, lang);
      setAnswer(result);
      setPlan("");
      pushLog(`$ agent.ask -> ${result.status} (${result.nodes.length} nodes)`);
    } catch (err) {
      setError((err as Error).message);
      pushLog(`! ${(err as Error).message}`);
    } finally {
      setBusy("");
    }
  }

  async function planOnly() {
    if (!question.trim()) return;
    setBusy("plan");
    setError("");
    try {
      const result = await api.agentPlan(question, lang);
      setPlan(result.explanation);
      setAnswer(null);
      pushLog("$ agent.plan");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-line px-3 py-3">
        <h2 className="text-sm font-semibold text-[rgb(var(--c-text))]">{translate(lang, "agentPanel")}</h2>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={3}
          placeholder={translate(lang, "agentQuestionHint")}
          className="w-full rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px] text-[rgb(var(--c-text))] outline-none focus:border-accent"
        />

        <label className="mt-2 flex items-center gap-2 text-[11px] text-[rgb(var(--c-text-faint))]">
          <input
            type="checkbox"
            checked={useLlm}
            onChange={(event) => setUseLlm(event.target.checked)}
            className="h-3.5 w-3.5 accent-accent"
          />
          {translate(lang, "agentUseLLM")}
        </label>

        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={ask}
            disabled={busy !== ""}
            className="rounded-md bg-accent px-3 py-1.5 text-[11px] font-semibold text-canvas hover:bg-accent/85 disabled:opacity-40"
          >
            {busy === "ask" ? `${translate(lang, "agentPlanning")}…` : translate(lang, "agentAsk")}
          </button>
          <button
            type="button"
            onClick={planOnly}
            disabled={busy !== ""}
            className="rounded-md border border-line px-3 py-1.5 text-[11px] text-[rgb(var(--c-text-dim))] hover:border-accent disabled:opacity-40"
          >
            {translate(lang, "agentPlanOnly")}
          </button>
        </div>

        {error && <p className="mt-2 text-[11px] text-bad">{error}</p>}

        {/* Offline notice (v0.7.3): the single most confusing thing about an
            agent without a key is that it still answers -- just by rules.  Say
            so here, next to the toggle that caused it, and offer the fix. */}
        {credentialCount === 0 && (
          <div className="mt-2 rounded-md border border-warn/40 bg-warn/10 px-2 py-1.5">
            <p className="text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
              {translate(lang, "keyMissingBanner")}
            </p>
            <button
              type="button"
              onClick={() => {
                if (!useEditor.getState().dockOpen) setDockOpen(true);
                setDockTab("apikey");
              }}
              className="mt-1 rounded border border-warn/60 px-2 py-0.5 text-[10px] font-medium text-warn transition hover:bg-warn/15"
            >
              {translate(lang, "keyOpenPanel")}
            </button>
          </div>
        )}

        {plan && (
          <section className="mt-4">
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
              {translate(lang, "agentPlan")}
            </h3>
            <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-canvas p-2 text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
              {plan}
            </pre>
          </section>
        )}

        {answer && (
          <>
            <section className="mt-4 space-y-1 rounded-md border border-line bg-canvas px-2 py-2 text-[11px]">
              <Row label={translate(lang, "agentIntent")} value={answer.intent} />
              <Row label={translate(lang, "agentEngine")} value={answer.engine} />
              <Row
                label={translate(lang, "agentStatus")}
                value={answer.status}
                className={STATUS_COLOR[answer.status] ?? "text-[rgb(var(--c-text-dim))]"}
              />
              <Row
                label={translate(lang, "agentNodes")}
                value={`${answer.nodes.length} · ${answer.duration_ms.toFixed(0)} ms`}
              />
            </section>

            <section className="mt-4">
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
                {translate(lang, "agentPlan")}
              </h3>
              <ol className="space-y-0.5">
                {answer.nodes.map((node, index) => (
                  <li key={`${node}-${index}`} className="font-mono text-[10px] text-[rgb(var(--c-text-faint))]">
                    {index + 1}. {node}
                  </li>
                ))}
              </ol>
              {answer.notes.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {answer.notes.map((note, index) => (
                    <li key={index} className="text-[10px] text-[rgb(var(--c-text-faint))]">
                      - {note}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="mt-4">
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent/80">
                {translate(lang, "agentConclusion")}
              </h3>
              <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-canvas p-2 text-[10px] leading-relaxed text-[rgb(var(--c-text-dim))]">
                {answer.conclusion || "—"}
              </pre>
            </section>

            {answer.findings.length > 0 && (
              <section className="mt-4">
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[rgb(var(--c-text-faint))]">
                  {answer.findings.length} findings
                </h3>
                <ul className="space-y-1">
                  {answer.findings.slice(0, 12).map((finding, index) => (
                    <li
                      key={index}
                      className="rounded border border-line bg-canvas px-2 py-1 text-[10px] leading-snug text-[rgb(var(--c-text-faint))]"
                    >
                      {finding.text}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  className = "text-[rgb(var(--c-text))]",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[rgb(var(--c-text-faint))]">{label}</span>
      <span className={`truncate font-mono ${className}`}>{value || "—"}</span>
    </div>
  );
}
