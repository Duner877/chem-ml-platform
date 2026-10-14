# Chem ML Platform — Node.js SDK

REST client and workflow runner for the Chem ML Platform backend.

## Install

```bash
npm install ./node_sdk/nodejs
# or, from this folder
npm install
```

## Usage

```js
import { ChemMLClient } from "chemml-node-sdk";

const client = new ChemMLClient("http://127.0.0.1:8000");

// liveness + catalogue
console.log(await client.health());        // { status: "ok", nodes: 77, ... }
const specs = await client.nodes("Questions");

// run a stored demo workflow
const run = await client.runWorkflow("01_unknown_compound_identification.json");
console.log(client.summary(run));          // "...: completed (10 nodes, 1020 ms, 0 failed)"

// run an inline graph
const inline = await client.run({
  name: "inline",
  nodes: [{ id: "a", type: "IRNode", params: { smiles: "CCO" } }],
  edges: [],
});
console.log(inline.status);
```

## Live event stream

```js
const run = await client.runWorkflow("02_battery_material_discovery.json");
const socket = client.stream(run.run_id);
client.on("event", (event) => console.log(event.type, event.node_id ?? ""));
```

## API

| Method | Description |
| --- | --- |
| `health()` | backend liveness and node count |
| `categories()` | node catalogue grouped by category |
| `nodes(category?)` | node specifications, optionally filtered |
| `node(type)` | specification of a single node type |
| `workflows()` | stored workflow summaries |
| `workflow(file)` | full workflow definition |
| `validate(workflow)` | structural validation without execution |
| `runWorkflow(file, inputs?)` | execute a stored workflow |
| `run(workflow)` | execute an inline workflow |
| `summary(result)` | one-line summary of a run result |
| `runMany(files)` | execute several workflows sequentially |
| `stream(runId)` | WebSocket live event stream |
