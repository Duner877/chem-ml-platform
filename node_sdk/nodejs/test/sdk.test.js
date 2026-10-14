import test from "node:test";
import assert from "node:assert/strict";

import { ChemMLClient, ChemMLError } from "../src/index.js";

/**
 * In-memory fetch stub that answers the endpoints the SDK uses.
 *
 * Each route is either a plain response body, or ``{ status, body }`` when a
 * non-200 status is needed.
 */
function stubFetch(routes) {
  return async (url, init = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const key = `${init.method ?? "GET"} ${path}`;
    const handler = routes[key];
    if (handler === undefined) {
      return new Response(JSON.stringify({ detail: `no route ${key}` }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    const resolved = typeof handler === "function" ? handler(init) : handler;
    const isWrapper =
      resolved !== null &&
      typeof resolved === "object" &&
      "body" in resolved &&
      typeof resolved.status === "number";
    const status = isWrapper ? resolved.status : 200;
    const body = isWrapper ? resolved.body : resolved;
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
}

test("health() returns the backend payload", async () => {
  const client = new ChemMLClient("http://api.test", {
    fetchImpl: stubFetch({
      "GET /api/health": { status: "ok", version: "0.7.2", nodes: 89 },
    }),
  });
  const health = await client.health();
  assert.equal(health.status, "ok");
  assert.equal(health.nodes, 89);
});

test("runWorkflow() posts the input payload", async () => {
  let seen = null;
  const client = new ChemMLClient("http://api.test", {
    fetchImpl: stubFetch({
      "POST /api/workflows/demo.json/run": (init) => {
        seen = JSON.parse(init.body);
        return { run_id: "r1", workflow: "demo", status: "completed", duration_ms: 12, records: {} };
      },
    }),
  });
  const run = await client.runWorkflow("demo.json", { n1: { text: "hi" } });
  assert.equal(run.status, "completed");
  assert.deepEqual(seen, { inputs: { n1: { text: "hi" } } });
  assert.match(client.summary(run), /completed \(0 nodes, 12 ms, 0 failed\)/);
});

test("HTTP errors are wrapped in ChemMLError with validation issues", async () => {
  const client = new ChemMLClient("http://api.test", {
    fetchImpl: stubFetch({
      "POST /api/workflows/validate": {
        status: 422,
        body: { detail: { issues: ["node 'a' has no type"] } },
      },
    }),
  });
  await assert.rejects(
    () => client.validate({ nodes: [] }),
    (error) => {
      assert.ok(error instanceof ChemMLError);
      assert.equal(error.status, 422);
      assert.match(error.message, /node 'a' has no type/);
      return true;
    }
  );
});

test("an unreachable backend raises a descriptive error", async () => {
  const client = new ChemMLClient("http://127.0.0.1:1", { timeoutMs: 1500 });
  await assert.rejects(() => client.health(), /cannot reach/);
});

test("validate issues are surfaced through run()", async () => {
  const client = new ChemMLClient("http://api.test", {
    fetchImpl: stubFetch({
      "POST /api/workflows/run": {
        status: 422,
        body: { detail: { issues: ["cycle detected: a -> b -> a"] } },
      },
    }),
  });
  await assert.rejects(() => client.run({ nodes: [], edges: [] }), /cycle detected/);
});
