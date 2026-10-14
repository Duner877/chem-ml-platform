# 工作流 JSON 格式

工作流是一个有向无环图（DAG），用一个 JSON 对象描述。规范第 11 节的**简写形式**和图形编辑器产出的**扩展形式**都被接受；`to_dict()` 始终输出扩展形式（简写形式的严格超集）。

## 1. 顶层结构

```json
{
  "name": "工作流名称",
  "description": "一句话说明这个工作流做什么",
  "version": "0.7.1",
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | ✅ | 显示名 |
| `description` | string | — | 说明 |
| `version` | string | — | 格式版本 |
| `nodes` | array | ✅ | 节点实例列表 |
| `edges` | array | ✅ | 连线列表，可为 `[]` |

## 2. 节点 `nodes[]`

```json
{
  "id": "ms_file",
  "type": "SpectrumFileNode",
  "label": "质谱文件",
  "position": { "x": 40, "y": 120 },
  "params": {
    "path": "datasets/demo/caffeine_ms.xy",
    "technique": "MS"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | ✅ | 工作流内唯一；缺省自动生成 `n_xxxxxxxx` |
| `type` | string | ✅ | 已注册的节点类名，如 `SpectrumFileNode` |
| `label` | string | — | 画布显示名，缺省用节点的 `name` |
| `position` | object | — | `{"x": 数字, "y": 数字}`，仅前端布局用 |
| `params` | object | — | 参数覆盖，键为 `ParameterSpec.name`；也接受别名 `parameters` |

**`params` 的取值会被 `ParameterSpec` 强转**：`"window": "11"` 会变成 `11`；枚举按 value 或 label 匹配。缺省的参数用节点声明的默认值。

## 3. 连线 `edges[]`

### 3.1 扩展形式（推荐）

```json
{
  "source": "ms_file",
  "source_port": "spectrum",
  "target": "ms_peaks",
  "target_port": "spectrum"
}
```

| 字段 | 说明 |
| --- | --- |
| `source` / `target` | 节点 `id` |
| `source_port` / `target_port` | 端口名（大小写不敏感）。缺省取该节点的**第一个**端口 |

### 3.2 简写形式（规范第 11 节）

```json
["ms_file", "ms_peaks"]
```

等价于取源节点第一个输出端口 → 目标节点第一个输入端口。也支持对象形式 `{"source": "a", "target": "b"}`。

### 3.3 类型兼容规则

连线在校验期检查，不兼容直接拒绝运行：

- 任一端声明 `Any` → 通配，永远兼容；
- 两端同类型 → 兼容；
- 命中隐式转换表 → 兼容：`ScientificReport → Text`、`Molecule → Text`、`Material → Text`；
- 其余 → 不兼容。

## 4. 校验规则

`POST /api/workflows/validate` 或 `Workflow.validate(registry)` 返回问题列表（空列表 = 通过）：

| 检查 | 失败信息示例 |
| --- | --- |
| 节点 ID 唯一 | `duplicate node id 'ms_file'` |
| 节点类型已注册 | `node 'x' has unknown type 'FooNode'` |
| 边引用的节点存在 | `edge references unknown node 'y'` |
| 端口存在 | `unknown input port 'spec' on 'XRDNode'` |
| 端口类型兼容 | `port type mismatch: Spectrum -> Molecule` |
| 必填输入已连接 | `input 'spectrum' is not connected` |
| 图无环 | `workflow contains a cycle: a -> b -> a` |

必填端口 = `optional=False` 的输入端口。未连接的必填输入会让工作流**无法运行**；未连接的可选端口在 `execute()` 中表现为键缺失。

## 5. 完整示例

```json
{
  "name": "未知化合物鉴定",
  "description": "咖啡因 EI-MS + 1H NMR + IR 多证据鉴定",
  "nodes": [
    {
      "id": "ms_file",
      "type": "SpectrumFileNode",
      "label": "质谱文件",
      "position": { "x": 40, "y": 40 },
      "params": { "path": "datasets/demo/caffeine_ms.xy", "technique": "MS" }
    },
    {
      "id": "ms_peaks",
      "type": "PeakPickingNode",
      "position": { "x": 300, "y": 40 },
      "params": { "height": 0.02, "distance": 3 }
    },
    {
      "id": "nmr",
      "type": "NMR1HNode",
      "position": { "x": 40, "y": 200 },
      "params": { "molecule": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "jitter": 0.0 }
    },
    {
      "id": "identify",
      "type": "UnknownCompoundNode",
      "position": { "x": 560, "y": 120 },
      "params": { "top_k": 5, "language": "zh" }
    },
    {
      "id": "report",
      "type": "ReportBuilderNode",
      "position": { "x": 820, "y": 120 },
      "params": { "title": "未知物鉴定报告", "format": "html" }
    }
  ],
  "edges": [
    ["ms_file", "ms_peaks"],
    { "source": "ms_peaks", "source_port": "spectrum", "target": "identify", "target_port": "spectrum" },
    { "source": "nmr", "source_port": "spectrum", "target": "identify", "target_port": "nmr" },
    { "source": "identify", "source_port": "report", "target": "report", "target_port": "inputs" }
  ]
}
```

（完整可运行版本见 `workflows/01_unknown_compound_identification.json`。）

## 6. 运行时输入注入

除了写死在 `params` 里，还可以在运行时向指定节点端口注入数据：

```python
engine.run(workflow, inputs={
    "nmr": {"molecule": "CCO"},
    "ms_file": {"spectrum": {... Spectrum dict ...}},
})
```

REST 形式：`POST /api/workflows/{file}/run`，body 为 `{"inputs": {...}}`。注入值必须是 JSON 可序列化的，引擎会按目标端口类型转换。

## 7. 前端序列化

React Flow 画布保存时：

- `nodes[].id` = React Flow 节点 id；
- `nodes[].position` = `{x, y}`（直接来自画布坐标）；
- `nodes[].params` = 检查器面板的当前值；
- `edges[]` 一律写扩展形式（含端口名）。

保存路径：`POST /api/workflows`（校验 + 落盘到 `workflows/`）。
