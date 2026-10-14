# API 参考

Base URL：`http://localhost:8000`，所有路由前缀 `/api`。交互式文档（Swagger UI）：<http://localhost:8000/api/docs>。

所有请求/响应均为 JSON。错误统一为 FastAPI 的 `{"detail": "..."}` 格式；校验失败为 `422` 且 `detail` 为问题列表或说明字符串。

## 1. 节点目录

### `GET /api/health`

```json
{ "status": "ok", "version": "0.7.1", "nodes": 89 }
```

### `GET /api/meta`

前端启动载荷：分类列表 + 全部节点规格 + 数据字典。页面加载时调用一次。

### `GET /api/nodes`

节点规格列表。查询参数：

| 参数 | 说明 |
| --- | --- |
| `category` | 精确匹配分类，如 `Instruments` |
| `query` | 关键字，匹配名称 / 类型 / 描述 / 标签（大小写不敏感） |

响应元素结构：

```json
{
  "type": "SpectrumFileNode",
  "name": "Spectrum File",
  "category": "IO",
  "description": "读取 mzML/mzXML/MGF/MSP/JCAMP/XY/Bruker 谱图文件",
  "version": "0.7.1",
  "tags": ["io", "spectrum"],
  "icon": "SF",
  "inputs":  [{ "name": "path", "data_type": "Any", "optional": false, "multi": false }],
  "outputs": [{ "name": "spectrum", "data_type": "Spectrum", "optional": false, "multi": false }],
  "parameters": [
    { "name": "path", "type": "path", "default": "", "description": "文件路径", "required": false }
  ]
}
```

### `GET /api/nodes/categories`

```json
[
  { "category": "IO", "count": 6, "nodes": ["SpectrumFileNode", "..."] }
]
```

驱动左侧节点面板的分组。

### `GET /api/nodes/{type}`

单个节点完整规格；未知类型返回 `404`。

## 2. 工作流

### `GET /api/workflows`

`workflows/` 目录下全部 JSON 的摘要：

```json
[{ "file": "01_unknown_compound_identification.json", "name": "...", "nodes": 10, "edges": 9 }]
```

### `GET /api/workflows/{filename}`

返回完整工作流 JSON（原样）。文件名做路径穿越防护，`404` 表示不存在。

### `POST /api/workflows`

校验并保存。请求体：

```json
{ "name": "我的工作流", "description": "", "nodes": [...], "edges": [...] }
```

- 成功：`201`，`{"file": "我的工作流.json", "name": "...", "nodes": 10}`
- 校验失败：`422`，`{"detail": {"issues": ["..."]}}`

文件名由 `name` 生成（安全字符、截断 80）。

### `POST /api/workflows/validate`

只校验不执行、不落盘：

```json
{ "valid": false, "issues": ["input 'spectrum' is not connected"] }
```

### `POST /api/workflows/{filename}/run`

执行已存储工作流。请求体可选：

```json
{ "inputs": { "nmr": { "molecule": "CCO" } }, "save": false }
```

响应 `RunResponse`：

```json
{
  "run_id": "api_1a2b3c4d5e6f",
  "workflow": "未知化合物鉴定",
  "status": "completed",
  "nodes": 10,
  "duration_ms": 1020.4,
  "records": {
    "ms_file": {
      "status": "completed",
      "duration_ms": 3.1,
      "logs": ["loaded caffeine_ms.xy (401 points)"],
      "outputs": { "spectrum": "Spectrum(...)" }
    }
  },
  "artifacts": ["output/api_runs/01_.../runs/api_.../artifacts/candidates.csv"],
  "errors": []
}
```

`status` ∈ `completed` / `failed`。校验失败返回 `422`。

### `POST /api/workflows/run`

执行请求体内的内联工作流（不落盘）。请求体与 `POST /api/workflows` 相同，响应同上。

### `GET /api/workflows/runs/{run_id}/events`

运行事件历史（不能WebSocket 时的轮询替代）：

```json
[{ "type": "run_started", "message": "start ...", "progress": 0.0, "run_id": "..." }]
```

事件类型：`run_started`、`node_started`、`node_log`、`node_completed`、`node_failed`、`node_skipped`、`node_cached`、`run_completed`、`run_failed`。

### `GET /api/workflows/runs/{run_id}`

`{"run_id": "...", "events": 42, "finished": true}`。未知 run 返回 `404`。

## 3. 运行与产物

### `GET /api/runs`

全部运行记录（扫描 `output/`），新的在前：

```json
[{
  "run_id": "20251012_143000_ab12cd",
  "workflow": "01_unknown_compound_identification",
  "path": "output/demo_runs/01_.../runs/20251012_143000_ab12cd",
  "artifacts": [".../artifacts/candidates.csv", ".../artifacts/report.html"]
}]
```

### `GET /api/runs/artifacts/{path}`

下载产物文件（CSV / JSON / Markdown / HTML / PNG）。`path` 为相对仓库根的路径，越界访问返回 `403`，不存在返回 `404`。

## 4. 基座模型 / AI / Agent / 数据 / 仿真（v0.6 新增）

### `GET /api/foundation/models`

基座模型目录（含实时可用性）：

```json
{
  "count": 9,
  "modalities": ["molecule", "spectrum", "material"],
  "models": [
    { "key": "chemberta", "name": "ChemBERTa", "family": "SMILES transformer",
      "modality": "molecule", "dimension": 384,
      "capabilities": ["embed", "similarity"],
      "requires_weights": true, "available": true,
      "backend": "torch", "input": "SMILES string",
      "output": "embedding + property head" }
  ]
}
```

共 9 个模型：ChemBERTa / GROVER / Graphormer / Uni-Mol / Morgan / Descriptor-Vector（molecule）、Physchem（molecule，`predict`）、Spectrum-Bin / Spectrum-Summary（spectrum）。

### `POST /api/foundation/embed`

```json
{ "items": ["CCO", "CCCO"], "model": "morgan", "modality": "molecule" }
```

返回单位向量：

```json
{ "count": 2, "dimension": 2048, "vectors": [[0.031, -0.012, ...], [...]] }
```

### `POST /api/foundation/similarity`

```json
{ "a": "CCO", "b": "CCCO", "metric": "cosine" }
```

```json
{ "a": "CCO", "b": "CCCO", "metric": "cosine", "similarity": 0.953221 }
```

`metric` ∈ `cosine`（默认）/ `euclidean`。乙醇 vs 苯为 `-0.323782`，符合化学直觉。

### `POST /api/foundation/predict`

```json
{ "items": ["CCO"], "property": "logp" }
```

```json
{ "count": 1, "property": "logp",
  "rows": [{ "smiles": "CCO", "value": 0.58, "unit": "", "confidence": 0.6,
             "engine": "internal:descriptors", "model": "Physchem", "property": "logp" }] }
```

可用属性：`logp` / `esol` / `heavy_atoms` / `mw` / `tpsa` 等（映射到真实描述符键）。

### `GET /api/ai/modes` · `GET /api/ai/providers`

`/ai/modes` 返回可选运行模式与中英文标签；`/ai/providers` 返回当前 `mode`、强制 `provider` 与逐供应商可用性（`ai_runtime.state()`）。

### `GET /api/ai/config` · `PUT /api/ai/config`

`GET` 返回当前配置，密钥以 `***` 掩码，并附 `api_keys_set` 布尔表：

```json
{ "mode": "auto", "provider": "", "model": "", "temperature": 0.2, "max_tokens": 1024,
  "timeout": 60.0, "api_keys": { "openai": "***" }, "api_keys_set": { "openai": true } }
```

`PUT` 为**部分更新**，仅改动提供的字段；`api_keys` 中的 `***` 或空字符串会被忽略（不会清空已存密钥）：

```json
{ "mode": "local", "provider": "ollama", "temperature": 0.0 }
```

### `POST /api/ai/complete`

```json
{ "prompt": "用一句话解释 EHT", "family": "auto", "context": "" }
```

返回补全文本与真实来源（外部分不可用时为 `built-in`，并在 `skipped` 中记录原因）。

### `POST /api/ai/test`

对当前模式做连通性自检，返回可用的 `family` 列表。

### `POST /api/agent/ask`

端到端运行 Agent：规划 → 执行 → 推理 → 报告。

```json
{ "question": "咖啡因的溶解度如何？", "language": "zh", "use_llm": true, "max_nodes": 12, "remember": false }
```

返回 `summarise(outputs)`：答案、依据（findings）、章节（sections）与工作流文本。

### `POST /api/agent/plan`

```json
{ "question": "设计一个电池材料筛选流程", "max_nodes": 12 }
```

```json
{ "workflow": "{...}", "explanation": "..." }
```

### `GET /api/agent/history?limit=20`

`{"stats": {...}, "workflows": [...], "knowledge": [...]}`（来自 `memory` 持久记忆）。

### `GET /api/data/catalog`

查询参数：`query` / `type` / `source` / `tag` / `limit` / `with_embedding`。返回 `{"count", "entries", "stats"}`。

### `GET /api/data/catalog/{entry_id}` · `GET /api/data/stats`

单个目录项 / 目录统计（`{"path", ...}`）。

### `POST /api/data/ingest`

```json
{ "path": "datasets/demo/caffeine_ms.xy", "tags": ["demo"], "note": "", "embed": true }
```

经数据层读入并索引每个对象；返回 `{"count", "entries", "stats"}`。

### `GET /api/data/datasets`

列出 `datasets/` 下可被 GUI 录入的数据文件。

### `GET /api/simulations/families` · `GET /api/simulations/backends`

仿真族（`quantum` / `md` / `materials`）与全部已注册后端及其可用性。

### `POST /api/simulations/run`

```json
{ "family": "quantum", "backend": "orca", "smiles": "CCO", "params": {},
  "force_internal": false, "timeout": 600, "wait": true }
```

`smiles` 与 `formula` 二选一（分子 / 材料）。`wait=true` 同步等待，`false` 返回作业句柄。响应为 `SimulationJob.to_dict()`。

### `GET /api/simulations/jobs?limit=50&family=` · `GET /api/simulations/jobs/{job_id}`

作业列表（新在前，含 `stats`）与单个作业；未知作业返回 `404`。

## 5. WebSocket

### `WS /api/ws/run/{run_id}`

实时事件流。连接后服务端先发一帧：

```json
{ "type": "connected", "run_id": "api_...", "message": "listening for events" }
```

随后每个引擎事件作为一帧 JSON 推送，直到运行结束或客户端断开。

典型用法：

```js
// 1. 先建 run_id（或让服务端在 POST 响应里返回）
const runId = "api_myrun";
const socket = new WebSocket(`ws://localhost:8000/api/ws/run/${runId}`);
socket.onmessage = (e) => console.log(JSON.parse(e.data).type);

// 2. 再发起执行
await fetch(`/api/workflows/01_unknown_compound_identification.json/run`, { method: "POST" });
```

Node SDK 已封装此流程：`client.stream(runId)`。

### `GET /api/ws/sessions`

调试用：每个 run_id 当前挂载的 socket 数。

## 6. Python SDK 快捷方式

手写 HTTP 请求时优先用 SDK（零依赖，`urllib` 实现）：

```python
from chemml_sdk import ChemMLClient

client = ChemMLClient("http://127.0.0.1:8000")
client.health()                       # GET /api/health
client.nodes(category="Instruments")  # GET /api/nodes?category=...
client.workflows()                    # GET /api/workflows
client.run_workflow("01_unknown_compound_identification.json")
client.run_events(run.run_id)
client.runs()
```

完整方法表见 [node_sdk/python/README.md](../node_sdk/python/README.md)。

## 7. 错误码速查

| 状态码 | 含义 | 常见原因 |
| --- | --- | --- |
| `404` | 资源不存在 | 工作流/节点/run/产物文件名拼错 |
| `422` | 校验失败 | 工作流有环、端口未连接、类型不兼容 |
| `403` | 路径穿越被拒 | 产物路径包含 `..` |
| `500` | 服务端异常 | 查看 uvicorn 日志；通常是节点抛了未捕获异常 |
