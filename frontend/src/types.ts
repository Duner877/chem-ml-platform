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
