/** Thin REST client for the Chem ML Platform backend. */

import type {
  AIConfig,
  AICompletion,
  AIModeInfo,
  AIState,
  AgentAnswer,
  AgentPlanResult,
  CatalogEntry,
  CatalogStats,
  CredentialProbe,
  CredentialProvider,
  CredentialStore,
  CredentialStoreResult,
  FileListing,
  FileProbe,
  FoundationModel,
  FragmentationResult,
  ProviderModelList,
  NodeCategory,
  NodeSpec,
  RegistryPayload,
  RunResult,
  SimilarityResult,
  SimulationBackend,
  SimulationJob,
  UpdateCheck,
  UpdateCurrent,
  UpdateDownload,
  WorkflowSummary,
} from "./types";

const BASE = "/api";

/**
 * Session token injected by the Electron shell (v0.7.1 task D).  In the browser
 * development flow it is absent and the backend runs in loopback dev mode; the
 * desktop build sets `window.__CHEMML_TOKEN__` from the launcher.
 */
function sessionToken(): string {
  const injected = (globalThis as { __CHEMML_TOKEN__?: string }).__CHEMML_TOKEN__;
  return typeof injected === "string" ? injected : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { "X-ChemML-Token": token } : {}),
  };
  const response = await fetch(`${BASE}${path}`, {
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail?.issues))
        detail = body.detail.issues.join("; ");
    } catch {
      /* keep the status line */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string; version: string; nodes: number }>("/health"),

  categories: () => request<NodeCategory[]>("/nodes/categories"),

  nodes: (category?: string) =>
    request<NodeSpec[]>(
      `/nodes${category ? `?category=${encodeURIComponent(category)}` : ""}`
    ),

  nodeSpec: (type: string) => request<NodeSpec>(`/nodes/${type}`),

  registry: () => request<RegistryPayload>("/nodes/registry/full"),

  workflows: () => request<WorkflowSummary[]>("/workflows"),

  workflow: (file: string) =>
    request<Record<string, unknown>>(`/workflows/${encodeURIComponent(file)}`),

  validate: (payload: unknown) =>
    request<{ valid: boolean; issues: string[] }>("/workflows/validate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  runWorkflow: (file: string, inputs?: Record<string, unknown>) =>
    request<RunResult>(
      `/workflows/${encodeURIComponent(file)}/run`,
      {
        method: "POST",
        body: JSON.stringify({ inputs: inputs ?? {} }),
      }
    ),

  runInline: (payload: unknown) =>
    request<RunResult>("/workflows/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- v0.6: AI runtime -------------------------------------------------- //
  aiModes: () => request<AIModeInfo[]>("/ai/modes"),
  aiProviders: () => request<AIState>("/ai/providers"),
  aiConfig: () => request<AIConfig>("/ai/config"),
  setAiConfig: (patch: Partial<AIConfig>) =>
    request<AIConfig>("/ai/config", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  aiComplete: (prompt: string, family = "auto", provider = "") =>
    request<AICompletion>("/ai/complete", {
      method: "POST",
      body: JSON.stringify({ prompt, family, provider }),
    }),

  // ---- v0.6: agent ------------------------------------------------------- //
  agentAsk: (question: string, useLlm = true, language = "zh") =>
    request<AgentAnswer>("/agent/ask", {
      method: "POST",
      body: JSON.stringify({ question, use_llm: useLlm, language }),
    }),
  agentPlan: (question: string, language = "zh") =>
    request<AgentPlanResult>("/agent/plan", {
      method: "POST",
      body: JSON.stringify({ question, language }),
    }),
  agentHistory: (limit = 20) =>
    request<{ stats: Record<string, unknown>; workflows: unknown[]; knowledge: unknown[] }>(
      `/agent/history?limit=${limit}`
    ),

  // ---- v0.6: data catalog ------------------------------------------------ //
  dataCatalog: (query = "", limit = 50) =>
    request<{ count: number; entries: CatalogEntry[]; stats: CatalogStats }>(
      `/data/catalog?query=${encodeURIComponent(query)}&limit=${limit}`
    ),
  dataStats: () => request<CatalogStats>("/data/stats"),
  dataIngest: (path: string, tags: string[] = [], note = "") =>
    request<{ count: number; entries: CatalogEntry[]; stats: CatalogStats }>(
      "/data/ingest",
      {
        method: "POST",
        body: JSON.stringify({ path, tags, note }),
      }
    ),
  datasets: () => request<Array<{ path: string; name: string; size: number }>>("/data/datasets"),

  // ---- v0.6: simulations ------------------------------------------------- //
  simBackends: () =>
    request<{ count: number; available: string[]; backends: SimulationBackend[] }>(
      "/simulations/backends"
    ),
  simRun: (payload: {
    family: string;
    backend?: string;
    smiles?: string;
    formula?: string;
    params?: Record<string, unknown>;
    force_internal?: boolean;
  }) =>
    request<SimulationJob>("/simulations/run", {
      method: "POST",
      body: JSON.stringify({ wait: true, ...payload }),
    }),
  simJobs: (limit = 30) =>
    request<{ count: number; stats: Record<string, unknown>; jobs: SimulationJob[] }>(
      `/simulations/jobs?limit=${limit}`
    ),

  // ---- v0.7.3: credentials (the GUI's API-key entry point) --------------- //
  // Separate from ``aiConfig`` on purpose: that endpoint edits behaviour, this
  // one manages secrets.  No response here ever carries a stored key.
  credentials: () => request<CredentialStore>("/credentials"),

  credentialProviders: () =>
    request<{ backend: string; providers: CredentialProvider[] }>(
      "/credentials/providers"
    ),

  setCredential: (provider: string, secret: string, baseUrl = "", model = "") =>
    request<CredentialStoreResult>("/credentials", {
      method: "POST",
      body: JSON.stringify({ provider, secret, base_url: baseUrl, model }),
    }),

  /**
   * Fetch the model catalogue this credential can address.
   *
   * A catalogue, not a verified availability list -- the response carries
   * `catalogue_only` so the GUI can say so.  Returns 200 with `ok: false` when
   * there is no key yet, because "save a key first" is a displayable answer.
   */
  providerModels: (provider: string) =>
    request<ProviderModelList>(
      `/credentials/${encodeURIComponent(provider)}/models`,
      { method: "GET" }
    ),

  /** Remember which model this provider should serve; "" restores the default. */
  setProviderModel: (provider: string, model: string) =>
    request<{ provider: string; model: string }>(
      `/credentials/${encodeURIComponent(provider)}/model`,
      { method: "PUT", body: JSON.stringify({ model }) }
    ),

  deleteCredential: (provider: string) =>
    request<CredentialStoreResult>(`/credentials/${encodeURIComponent(provider)}`, {
      method: "DELETE",
    }),

  testCredential: (provider: string) =>
    request<CredentialProbe>(
      `/credentials/${encodeURIComponent(provider)}/test`,
      { method: "POST" }
    ),

  // ---- v0.7.2: local file browsing (file-parameter picker) --------------- //
  browseFiles: (path = "") =>
    request<FileListing>(`/files/browse?path=${encodeURIComponent(path)}`),

  probeFile: (path: string) =>
    request<FileProbe>(`/files/exists?path=${encodeURIComponent(path)}`),

  // ---- v0.7.2: fragmentation pathway deduction -------------------------- //
  fragmentationPathway: (payload: {
    spectrum: unknown;
    molecule?: unknown;
    smiles?: string;
    tolerance_ppm?: number;
    max_steps?: number;
    max_depth?: number;
    min_relative?: number;
    use_ai?: boolean;
    language?: string;
  }) =>
    request<FragmentationResult>("/agent/fragmentation", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // ---- v0.6: foundation models ------------------------------------------- //
  foundationModels: () =>
    request<{ count: number; modalities: string[]; models: FoundationModel[] }>(
      "/foundation/models"
    ),
  foundationSimilarity: (a: string, b: string, model = "") =>
    request<SimilarityResult>("/foundation/similarity", {
      method: "POST",
      body: JSON.stringify({ a, b, model }),
    }),

  // ---- v0.7.4: software update ------------------------------------------- //
  updateCurrent: () => request<UpdateCurrent>("/update/current"),

  updateCheck: () => request<UpdateCheck>("/update/check"),

  updateDownload: (url: string, filename?: string) =>
    request<UpdateDownload>("/update/download", {
      method: "POST",
      body: JSON.stringify({ url, filename }),
    }),
};

/** Websocket URL for a live run stream. */
export function runSocket(runId: string): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(
    `${protocol}://${window.location.host}${BASE}/ws/run/${runId}`
  );
}
