# chemml-sdk

Python SDK for **Chem ML Platform v0.7.2**.

Two things in one small package:

1. **Node authoring primitives** — `ScientificNode`, `Port`, `ParameterSpec`,
   `register_node` so a third-party node is a single `.py` file that imports
   nothing but `chemml_sdk`.
2. **`ChemMLClient`** — a dependency-free (`urllib` only) REST client for
   driving a running platform, plus `run_local()` for in-process execution
   without any HTTP backend.

## Install

```bash
pip install -e ./node_sdk/python        # editable, from the repo root
# or, from inside the directory:
pip install -e .
```

Zero runtime dependencies. The package re-exports the engine primitives it
needs from `workflow_engine`, which must be importable (i.e. run from the
repository root, or install the platform itself).

## Writing a node

```python
# plugins/my_node.py
from chemml_sdk import ScientificNode, Port, ParameterSpec, register_node
from workflow_engine.objects import Text

@register_node
class HelloNode(ScientificNode):
    name = "Hello Science"
    category = "Custom"
    description = "Greet the operator."
    version = "1.0.0"
    tags = ["demo"]

    input_ports = [Port("text", "Text", optional=True, multi=True)]
    output_ports = [Port("text", "Text")]

    parameters = [
        ParameterSpec("who", "string", "world", "Whom to greet"),
        ParameterSpec("times", "integer", 1, "Repeat count", min=1, max=10),
    ]

    def execute(self, inputs, ctx=None):
        who = self.get_param("who")
        times = int(self.get_param("times") or 1)
        self.log(f"greeting {who} {times}x")
        return {"text": Text(text=f"hello {who}! " * times)}
```

Drop the file into `plugins/` (or any directory named by `CHEMML_PLUGINS`)
and it is registered on the next discovery pass:

```bash
CHEMML_PLUGINS=./plugins python -m nodes.loader --stats
```

### The node contract

| Rule | Detail |
| --- | --- |
| Base class | Subclass `ScientificNode`, implement `execute(self, inputs, ctx=None) -> dict` |
| Inputs | `inputs` keys are input-port names; values are scientific objects (or lists when the port is `multi=True`) |
| Outputs | Returned dict keys must match the declared output-port names |
| Optional ports | Declare `Port(..., optional=True)`; the key is simply absent from `inputs` when nothing is connected |
| Parameters | Read with `self.get_param(name)` — values are already coerced by `ParameterSpec` |
| Logging | `self.log("message")` streams to the console and the WebSocket event feed |
| Failures | Any exception marks the node failed and downstream nodes are skipped automatically |

### `ParameterSpec`

```python
ParameterSpec(
    name, type, default, description,
    options=None,   # [value, label] pairs -> rendered as a dropdown
    min=None, max=None,
    required=False,
)
```

Supported types: `string`, `text`, `integer`, `float`, `number`, `boolean`,
`enum`, `path`, `file`, `molecule`, `material`, `list`, `dict`.

### `Port`

```python
Port(name, data_type="Any", description="", optional=False, multi=False)
```

`data_type` is one of `DATA_TYPES`:
`Any`, `Spectrum`, `Molecule`, `Material`, `Table`, `Image`,
`SpectralMatch`, `Reaction`, `Text`, `ScientificReport`.

`Any` is a wildcard. Implicit casts are applied automatically:
`ScientificReport → Text`, `Molecule → Text`, `Material → Text`.

## HTTP client

```python
from chemml_sdk import ChemMLClient

client = ChemMLClient("http://127.0.0.1:8000")

client.health()                      # {'status': 'ok', 'nodes': 85, ...}
client.nodes(category="Instruments")
client.node("SpectrumFileNode")      # full spec: ports, parameters, metadata
client.workflows()                   # stored workflows
client.workflow("01_unknown_compound_identification.json")
client.validate({"name": "x", "nodes": [...], "edges": [...]})

run = client.run_workflow("01_unknown_compound_identification.json")
print(client.summary(run))           # "01_...: completed (10 nodes, 1020 ms, 0 failed)"

# In-process execution — no HTTP server required
result = client.run_local({"name": "inline", "nodes": [...], "edges": [...]})
```

### API surface

| Method | HTTP | Description |
| --- | --- | --- |
| `health()` | `GET /api/health` | liveness + node count |
| `categories()` | `GET /api/nodes/categories` | catalogue grouped by category |
| `nodes(category=None, query=None)` | `GET /api/nodes` | node list |
| `node(type)` | `GET /api/nodes/{type}` | one node spec |
| `workflows()` | `GET /api/workflows` | stored workflow files |
| `workflow(name)` | `GET /api/workflows/{name}` | load a workflow |
| `save_workflow(doc)` | `POST /api/workflows` | validate + store |
| `validate(doc)` | `POST /api/workflows/validate` | validation only |
| `run_workflow(name)` | `POST /api/workflows/{name}/run` | run a stored workflow |
| `run(doc)` | `POST /api/workflows/run` | run an inline workflow |
| `runs()` | `GET /api/runs` | run history |
| `run_events(run_id)` | `GET /api/workflows/runs/{id}/events` | event history |
| `run_detail(run_id)` | `GET /api/workflows/runs/{id}` | full run record + artefacts |
| `artifact_url(path)` | `GET /api/runs/artifacts/{path}` | download URL for an artefact |
| `run_local(doc)` | — | execute in-process via `WorkflowEngine` |
| `summary(run)` | — | one-line human-readable verdict |
| `node_types()` | — | every node type of the local install |

## License

Apache License 2.0 — see [../../LICENSE](../../LICENSE).
