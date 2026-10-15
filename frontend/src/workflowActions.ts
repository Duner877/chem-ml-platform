/** Run / validate actions shared by the top menu and the bottom run bar. */

import { useEditor } from "./store";
import { api } from "./api";

export function useRunActions() {
  const {
    nodes,
    edges,
    lang,
    resetStatus,
    setBusy,
    setRunResult,
    pushLog,
    setNotice,
  } = useEditor();

  function buildPayload() {
    return {
      name: "Editor Workflow",
      nodes: nodes.map((node) => {
        const data = node.data as unknown as {
          type: string;
          label: string;
          label_en: string;
          params: Record<string, unknown>;
        };
        return {
          id: node.id,
          type: data.type,
          // Persist both display labels so a reload keeps the chosen language.
          label: data.label,
          label_en: data.label_en,
          params: data.params,
          position: { x: node.position.x, y: node.position.y },
        };
      }),
      edges: edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        source_port: edge.sourceHandle ?? undefined,
        target_port: edge.targetHandle ?? undefined,
      })),
    };
  }

  async function handleRun() {
    resetStatus();
    setBusy(true);
    setRunResult(null);
    pushLog(`$ run workflow (${nodes.length} nodes / ${edges.length} edges)`);
    try {
      const result = await api.runInline(buildPayload());
      setRunResult(result);
      for (const [nodeId, record] of Object.entries(result.records ?? {})) {
        pushLog(
          `[${record.status}] ${nodeId} (${record.duration_ms.toFixed(0)} ms)` +
            (record.error ? ` — ${record.error}` : "")
        );
        for (const line of record.logs ?? []) pushLog(`    ${line}`);
      }
      pushLog(
        result.errors.length
          ? `! ${result.errors.length} node(s) failed`
          : `✔ run ${result.run_id} finished in ${result.duration_ms.toFixed(0)} ms`
      );
      setNotice(result.status);
    } catch (error) {
      pushLog(`! ${(error as Error).message}`);
      setNotice("failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleValidate() {
    try {
      const result = await api.validate(buildPayload());
      pushLog(
        result.valid
          ? "✔ workflow is valid"
          : `✘ ${result.issues.length} issue(s):\n${result.issues.join("\n")}`
      );
      setNotice(result.valid ? "valid" : "invalid");
    } catch (error) {
      pushLog(`! ${(error as Error).message}`);
    }
  }

  // ``lang`` keeps the closure honest for the agent language parameter.
  void lang;
  return { buildPayload, handleRun, handleValidate };
}
