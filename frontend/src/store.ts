/** Zustand store holding the editor state. */

import { create } from "zustand";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from "@xyflow/react";

import type { NodeSpec, RunResult } from "./types";
import type { Lang } from "./i18n";

export type NodeStatus = "idle" | "running" | "completed" | "failed" | "skipped";

/** Tabs of the right hand workbench dock. */
export type DockTab = "inspector" | "ai" | "agent" | "data" | "simulation";

export interface EditorState {
  lang: Lang;
  specs: Record<string, NodeSpec>;
  categories: { name: string; count: number }[];
  nodes: Node[];
  edges: Edge[];
  selectedId: string | null;
  search: string;
  status: NodeStatus;
  logs: string[];
  marketplaceOpen: boolean;
  dockTab: DockTab;
  runResult: RunResult | null;
  backend: "unknown" | "online" | "offline";
  busy: boolean;
  notice: string;

  setLang: (lang: Lang) => void;
  toggleLang: () => void;
  setSpecs: (specs: NodeSpec[]) => void;
  setSearch: (query: string) => void;
  setMarketplace: (open: boolean) => void;
  setDockTab: (tab: DockTab) => void;
  setBackend: (state: "unknown" | "online" | "offline") => void;
  setSelected: (id: string | null) => void;
  setBusy: (busy: boolean) => void;
  setNotice: (message: string) => void;

  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;

  addNode: (type: string, position?: { x: number; y: number }) => void;
  duplicateNode: (id: string) => void;
  removeNode: (id: string) => void;
  updateParams: (id: string, params: Record<string, unknown>) => void;
  updateLabel: (id: string, label: string) => void;
  setStatus: (id: string, status: NodeStatus) => void;
  clearCanvas: () => void;

  loadWorkflow: (payload: {
    name?: string;
    nodes?: unknown[];
    edges?: unknown[];
  }) => void;
  setRunResult: (result: RunResult | null) => void;
  pushLog: (line: string) => void;
  resetStatus: () => void;
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter}`;
}

function defaultParams(spec: NodeSpec): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const parameter of spec.parameters) {
    params[parameter.name] = parameter.default;
  }
  return params;
}

export const useEditor = create<EditorState>((set, get) => ({
  lang: "zh",
  specs: {},
  categories: [],
  nodes: [],
  edges: [],
  selectedId: null,
  search: "",
  status: "idle",
  logs: [],
  marketplaceOpen: false,
  dockTab: "inspector",
  runResult: null,
  backend: "unknown",
  busy: false,
  notice: "",

  setLang: (lang) => set({ lang }),
  toggleLang: () => set({ lang: get().lang === "zh" ? "en" : "zh" }),
  setSpecs: (specs) =>
    set({
      specs: Object.fromEntries(specs.map((spec) => [spec.type, spec])),
      categories: Object.entries(
        specs.reduce<Record<string, number>>((acc, spec) => {
          acc[spec.category] = (acc[spec.category] ?? 0) + 1;
          return acc;
        }, {})
      )
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    }),
  setSearch: (search) => set({ search }),
  setMarketplace: (open) => set({ marketplaceOpen: open }),
  setDockTab: (dockTab) => set({ dockTab }),
  setBackend: (backend) => set({ backend }),
  setSelected: (selectedId) => set({ selectedId }),
  setBusy: (busy) => set({ busy }),
  setNotice: (notice) => set({ notice }),

  onNodesChange: (changes: NodeChange[]) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),

  onEdgesChange: (changes: EdgeChange[]) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),

  onConnect: (connection: Connection) =>
    set({
      edges: addEdge(
        {
          ...connection,
          id: nextId("e"),
          animated: true,
        },
        get().edges
      ),
    }),

  addNode: (type, position) => {
    const spec = get().specs[type];
    if (!spec) return;
    const id = nextId("n");
    const node: Node = {
      id,
      type: "scientific",
      position: position ?? {
        x: 80 + Math.random() * 320,
        y: 60 + Math.random() * 320,
      },
      data: {
        type,
        label: spec.name,
        spec,
        params: defaultParams(spec),
        status: "idle" as NodeStatus,
        logs: [],
      },
    };
    set({ nodes: [...get().nodes, node], selectedId: id });
  },

  duplicateNode: (id) => {
    const source = get().nodes.find((node) => node.id === id);
    if (!source) return;
    const newId = nextId("n");
    set({
      nodes: [
        ...get().nodes,
        {
          ...source,
          id: newId,
          position: {
            x: source.position.x + 60,
            y: source.position.y + 60,
          },
          selected: false,
          data: { ...source.data, status: "idle", logs: [] },
        },
      ],
      selectedId: newId,
    });
  },

  removeNode: (id) =>
    set({
      nodes: get().nodes.filter((node) => node.id !== id),
      edges: get().edges.filter(
        (edge) => edge.source !== id && edge.target !== id
      ),
      selectedId: get().selectedId === id ? null : get().selectedId,
    }),

  updateParams: (id, params) =>
    set({
      nodes: get().nodes.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, params } }
          : node
      ),
    }),

  updateLabel: (id, label) =>
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, label } } : node
      ),
    }),

  setStatus: (id, status) =>
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, status } } : node
      ),
    }),

  clearCanvas: () => set({ nodes: [], edges: [], selectedId: null, runResult: null }),

  loadWorkflow: (payload) => {
    const specs = get().specs;
    const rawNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const rawEdges = Array.isArray(payload.edges) ? payload.edges : [];

    const idMap: Record<string, string> = {};
    const nodes: Node[] = [];

    for (const raw of rawNodes) {
      const item = raw as {
        id?: string;
        type?: string;
        params?: Record<string, unknown>;
        position?: { x: number; y: number };
        label?: string;
      };
      const spec = specs[item.type ?? ""];
      if (!spec) continue;
      const id = item.id ?? nextId("n");
      idMap[String(item.id ?? id)] = id;
      nodes.push({
        id,
        type: "scientific",
        position: item.position ?? {
          x: 80 + nodes.length * 70,
          y: 60 + nodes.length * 50,
        },
        data: {
          type: item.type,
          label: item.label || spec.name,
          spec,
          params: { ...defaultParams(spec), ...(item.params ?? {}) },
          status: "idle",
          logs: [],
        },
      });
    }

    const edges: Edge[] = [];
    for (const raw of rawEdges) {
      const item = raw as {
        source?: string;
        target?: string;
        source_port?: string;
        target_port?: string;
      };
      const source = idMap[String(item.source)];
      const target = idMap[String(item.target)];
      if (!source || !target) continue;
      edges.push({
        id: nextId("e"),
        source,
        target,
        sourceHandle: item.source_port ?? null,
        targetHandle: item.target_port ?? null,
        animated: true,
      });
    }

    set({ nodes, edges, selectedId: null, runResult: null });
  },

  setRunResult: (runResult) => set({ runResult }),
  pushLog: (line) => set({ logs: [...get().logs, line] }),
  resetStatus: () =>
    set({
      status: "idle",
      logs: [],
      nodes: get().nodes.map((node) => ({
        ...node,
        data: { ...node.data, status: "idle", logs: [] },
      })),
    }),
}));
