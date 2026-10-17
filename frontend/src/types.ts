/** Shared data contracts between the backend and the editor. */

export interface NodeParamSpec {
  name: string;
  type: "string" | "text" | "number" | "integer" | "boolean" | "enum" | "file";
  default: unknown;
  description: string;
  /** English mirror of ``description`` (see backend ``node_i18n``). */
  description_en: string;
  options: unknown[];
  /** English labels for ``(value, label)`` enum options. */
  options_en: unknown[];
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string;
  advanced: boolean;
}

export interface PortSpec {
  name: string;
  data_type: string;
  description: string;
  /** English mirror of ``description`` (see backend ``node_i18n``). */
  description_en: string;
  optional: boolean;
  multi: boolean;
}

export interface NodeSpec {
  type: string;
  /** Canonical (English) display name. */
  name: string;
  /** Chinese display name (see backend ``node_i18n``). */
  name_zh: string;
  category: string;
  /** Chinese display name of the category. */
  category_zh: string;
  description: string;
  /** English mirror of ``description``. */
  description_en: string;
  version: string;
  icon: string;
  tags: string[];
  aliases: string[];
  inputs: PortSpec[];
  outputs: PortSpec[];
  parameters: NodeParamSpec[];
}

export interface NodeCategory {
  name: string;
  count: number;
  nodes: NodeSpec[];
}

export interface WorkflowNodeData extends Record<string, unknown> {
  type: string;
  /** Chinese display label (demo label or the node's Chinese name). */
  label: string;
  /** English display label (demo ``label_en`` or the canonical node name). */
  label_en: string;
  spec: NodeSpec;
  params: Record<string, unknown>;
  status?: "idle" | "running" | "completed" | "failed" | "skipped";
  logs?: string[];
}

export interface WorkflowSummary {
  file: string;
  name: string;
  description: string;
  nodes: number;
  edges: number;
}

export interface RegistryNode {
  node_name: string;
  /** Chinese display name (see backend ``node_i18n``). */
  name_zh: string;
  type: string;
  version: string;
  category: string;
  /** Chinese display name of the category. */
  category_zh: string;
  description: string;
  /** English mirror of ``description``. */
  description_en: string;
  tags: string[];
  author: string;
  module: string;
  inputs: string[];
  outputs: string[];
}

export interface RegistryPayload {
  package: string;
  total_nodes: number;
  categories: string[];
  nodes: RegistryNode[];
  valid?: boolean;
}

export interface NodeRecord {
  node_id: string;
  node_type: string;
  status: string;
  duration_ms: number;
  error: string;
  logs: string[];
  cached: boolean;
  progress: number;
  /** Serialized port values (``serialize_object`` output) when present. */
  outputs?: Record<string, unknown>;
}

export interface RunResult {
  run_id: string;
  workflow: string;
  status: string;
  nodes: number;
  duration_ms: number;
  records: Record<string, NodeRecord>;
  artifacts: string[];
  errors: Array<{ node_id: string; node_type: string; error: string }>;
}

// --------------------------------------------------------------------------- //
// v0.6 — AI runtime, foundation models, data catalog, simulations, agent
// --------------------------------------------------------------------------- //
export interface AIModeInfo {
  mode: string;
  labels: Record<string, string>;
}

export interface AIProvider {
  name: string;
  family: string;
  model: string;
  description: string;
  available: boolean;
  reason: string;
  capabilities: string[];
  env_keys: string[];
}

export interface AIState {
  mode: string;
  provider: string;
  model: string;
  available: string[];
  providers: AIProvider[];
}

export interface AIConfig {
  mode: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  timeout: number;
  api_keys: Record<string, string>;
  base_urls: Record<string, string>;
  api_keys_set?: Record<string, boolean>;
}

export interface AICompletion {
  text: string;
  engine: string;
  family: string;
  model: string;
  provider: string;
  latency_ms: number;
  confidence: number;
  metadata: Record<string, unknown>;
}

/** One provider's credential, described without disclosing the secret. */
export interface CredentialStatus {
  provider: string;
  /** Chinese and English display names. */
  labels: Record<string, string>;
  /** ``"cloud"`` for a hosted API, ``"local"`` for Ollama / vLLM. */
  kind: string;
  env_var: string;
  configured: boolean;
  /** Where the value came from: environment, keyring, file or none. */
  source: string;
  /** e.g. ``sk-a•••••3456`` — never the whole secret. */
  masked: string;
  length: number;
  docs_url: string;
  notes: Record<string, string>;
  default_base_url: string;
}

/** The catalogue entry used to render the picker before anything is stored. */
export interface CredentialProvider {
  id: string;
  labels: Record<string, string>;
  kind: string;
  env_var: string;
  docs_url: string;
  default_base_url: string;
  notes: Record<string, string>;
}

export interface CredentialStore {
  /** ``"keyring"``, ``"file"`` — where a newly added key would land. */
  backend: string;
  backend_label: Record<string, string>;
  /** Present only when the backend is a plain file; bilingual. */
  warning: Record<string, string> | null;
  credentials: CredentialStatus[];
}

export interface CredentialStoreResult {
  provider: string;
  status: CredentialStore;
  masked?: string;
  stored_in?: string;
  removed?: boolean;
}

export interface CredentialProbe {
  provider: string;
  /** A rejected key is ``ok: false`` with a 200, not an exception. */
  ok: boolean;
  detail: string;
  latency_ms?: number;
  model?: string;
  /**
   * Machine-readable failure class (v0.7.3).  The GUI uses it to colour and
   * word the result: `invalid_key` means "check the key", while
   * `model_unsupported`, `network_unreachable` and `rate_limited` all report
   * `ok: false` but call for completely different user actions.  Optional
   * because an older backend does not send it.
   */
  outcome?: string;
  /** Present only when a custom base URL was probed, so failures are debuggable. */
  base_url?: string;
}

export interface AgentFinding {
  text: string;
  status: string;
}

export interface AgentSection {
  heading: string;
  body: string;
}

export interface AgentAnswer {
  question: string;
  intent: string;
  engine: string;
  nodes: string[];
  notes: string[];
  status: string;
  duration_ms: number;
  conclusion: string;
  findings: AgentFinding[];
  report_title: string;
  sections: AgentSection[];
  errors?: Array<{ node_id: string; node_type: string; error: string }>;
}

export interface AgentPlanResult {
  workflow: string;
  explanation: string;
}

export interface CatalogEntry {
  id: string;
  data_id: string;
  type: string;
  source: string;
  format: string;
  data_pointer: string;
  sample: string;
  instrument: string;
  engine: string;
  tags: string[];
  note: string;
  created_at: string;
  embedding_dim?: number;
  embedding_model?: string;
}

export interface CatalogStats {
  path: string;
  count: number;
  types: Record<string, number>;
  tags: string[];
  embedded: number;
}

export interface SimulationBackend {
  name: string;
  family: string;
  executable: string;
  is_external: boolean;
  available: boolean;
}

export interface SimulationJob {
  id: string;
  family: string;
  backend: string;
  status: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  engine: string;
  message: string;
  metrics: Record<string, number>;
  ports: Record<string, string>;
  workdir: string;
  error: string;
  params: Record<string, unknown>;
}

export interface FoundationModel {
  key: string;
  name: string;
  family: string;
  modality: string;
  dimension: number;
  capabilities: string[];
  properties: string[];
  description: string;
  available: boolean;
  requires_weights: boolean;
  reference: string;
  task?: string;
  backend?: string;
  input?: string;
  output?: string;
}

export interface SimilarityResult {
  a: string;
  b: string;
  metric: string;
  similarity: number;
}

// --------------------------------------------------------------------------- //
// v0.7.2 — local file browsing + fragmentation pathway deduction
// --------------------------------------------------------------------------- //

/** ``GET /api/files/exists`` result. */
export interface FileProbe {
  path: string;
  exists: boolean;
  is_dir: boolean;
  size: number | null;
}

/** One entry of ``GET /api/files/browse``. */
export interface FileEntry {
  name: string;
  path: string;
  size?: number | null;
  /** False for a file no importer node can open (shown greyed out). */
  readable?: boolean;
}

/** One directory listing. */
export interface FileListing {
  path: string;
  name: string;
  /** Empty string when the directory is a filesystem root. */
  parent: string;
  directories: FileEntry[];
  files: FileEntry[];
  truncated: boolean;
}

/** One step of a deduced fragmentation pathway. */
export interface FragmentationStep {
  step: number;
  /** Cleavage class or neutral loss, e.g. ``benzylic C–C`` / ``-H2O``. */
  rule: string;
  rationale: string;
  /** Formula of the fragment ion (empty for a structure-free deduction). */
  fragment_formula?: string;
  theoretical_mz: number;
  observed_mz: number;
  loss_da: number;
  relative_intensity: number;
  mass_error_ppm: number;
  confidence: number;
}

/** ``POST /api/agent/fragmentation`` response. */
export interface FragmentationResult {
  /** Rows aligned with ``columns``. */
  pathway: unknown[][];
  columns: string[];
  metadata: {
    engine?: string;
    confidence?: number;
    precursor_mz?: number | null;
    precursor_source?: string;
    precursor_neutral?: number | null;
    structure_known?: boolean;
    matched_peaks?: number;
    observed_peaks?: number;
    /** The de-adducted neutral molecule ion, when it was observed.  It breaks
     *  no bond, so the engine reports it separately rather than as a step. */
    de_adducted?: {
      rule?: string;
      theoretical_mz?: number;
      observed_mz?: number;
      mass_error_ppm?: number;
      relative_intensity?: number;
    } | null;
  };
  /** The deterministic rule engine's own account. */
  rules_text: string;
  /** AI interpretation, or the rule text with an explicit offline note. */
  narrative: string;
  /** Which engine produced the pathway. */
  engine: string;
  /** Which engine produced the narrative (``external:<provider>`` when a model). */
  ai_engine: string;
  confidence: number;
}
