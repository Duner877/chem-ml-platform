/**
 * Chem ML Platform -- Node.js SDK.
 *
 * @example
 * import { ChemMLClient } from "chemml-node-sdk";
 *
 * const client = new ChemMLClient("http://127.0.0.1:8000");
 * console.log(await client.health());          // { status: "ok", nodes: 77 }
 * const run = await client.runWorkflow("01_unknown_compound_identification.json");
 * console.log(run.status);                     // "completed"
 */

import { EventEmitter } from "node:events";

export class ChemMLError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "ChemMLError";
    this.status = status;
    this.detail = detail;
  }
}

export class ChemMLClient extends EventEmitter {
  /**
   * @param {string} baseUrl backend origin, e.g. "http://127.0.0.1:8000"
   * @param {{ timeoutMs?: number, fetchImpl?: typeof fetch }} [options]
   */
  constructor(baseUrl = "http://127.0.0.1:8000", options = {}) {
    super();
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this._fetch = options.fetchImpl ?? globalThis.fetch;
  }

  // ---------------------------------------------------------------- transport
  async #request(method, path, payload) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this._fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Accept: "application/json",
          ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      });
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      if (!response.ok) {
        const detail = body?.detail ?? body ?? response.statusText;
        const message = Array.isArray(detail?.issues)
          ? detail.issues.join("; ")
          : String(detail);
        throw new ChemMLError(
          `${method} ${path} failed (${response.status}): ${message}`,
          response.status,
          detail
        );
      }
      return body;
    } catch (error) {
      if (error instanceof ChemMLError) throw error;
      if (error?.name === "AbortError") {
        throw new ChemMLError(`request timed out after ${this.timeoutMs} ms`);
      }
      throw new ChemMLError(
        `cannot reach ${this.baseUrl} -- is the backend running? (${error?.cause?.code ?? error?.message ?? error})`
      );
    } finally {
      clearTimeout(timer);
    }
  }

  // ------------------------------------------------------------------- nodes
  health() {
    return this.#request("GET", "/api/health");
  }

  categories() {
    return this.#request("GET", "/api/nodes/categories");
  }

  /** @returns {Promise<Array<object>>} */
  nodes(category = "") {
    const suffix = category ? `?category=${encodeURIComponent(category)}` : "";
    return this.#request("GET", `/api/nodes${suffix}`);
  }

  node(nodeType) {
    return this.#request("GET", `/api/nodes/${nodeType}`);
  }

  // --------------------------------------------------------------- workflows
  workflows() {
    return this.#request("GET", "/api/workflows");
  }

  workflow(filename) {
    return this.#request("GET", `/api/workflows/${encodeURIComponent(filename)}`);
  }

  validate(workflow) {
    return this.#request("POST", "/api/workflows/validate", workflow);
  }

  /** Execute a stored workflow. */
  runWorkflow(filename, inputs = {}) {
    return this.#request(
      "POST",
      `/api/workflows/${encodeURIComponent(filename)}/run`,
      { inputs }
    );
  }

  /** Execute an inline workflow definition. */
  run(workflow) {
    return this.#request("POST", "/api/workflows/run", workflow);
  }

  /** One-line human readable summary of a run result. */
  summary(result) {
    const records = result.records ?? {};
    const failed = Object.entries(records).filter(
      ([, record]) => record.status === "failed"
    ).length;
    return `${result.workflow}: ${result.status} (${Object.keys(records).length} nodes, ${Math.round(result.duration_ms ?? 0)} ms, ${failed} failed)`;
  }

  /** Run several stored workflows sequentially. */
  async runMany(filenames) {
    const results = [];
    for (const filename of filenames) {
      // eslint-disable-next-line no-await-in-loop
      const result = await this.runWorkflow(filename);
      this.emit("run", result);
      results.push(result);
    }
    return results;
  }

  // ------------------------------------------------------------ live stream
  /**
   * Stream engine events for a run over WebSocket.
   *
   * @param {string} runId the id returned by runWorkflow / run
   * @returns {WebSocket} the raw socket; events arrive via the "event" emitter
   */
  stream(runId) {
    const url = new URL(this.baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = `/api/ws/run/${runId}`;
    const socket = new WebSocket(url);
    socket.addEventListener("message", (event) => {
      try {
        this.emit("event", JSON.parse(event.data));
      } catch {
        this.emit("event", { type: "raw", data: event.data });
      }
    });
    socket.addEventListener("error", () => this.emit("error", runId));
    return socket;
  }
}

export default ChemMLClient;
