# 节点开发指南

一个科学节点 = 一个 Python 类 + 一个装饰器。本文从零讲清契约、端口、参数、调试与测试。

## 1. 最小可运行节点

```python
# examples/plugins/melting_point_note.py
from chemml_sdk import ParameterSpec, Port, ScientificNode, register_node
from workflow_engine.objects import Text


@register_node
class MeltingPointNoteNode(ScientificNode):
    """把熔点记录整理成一行文本备注。"""

    name = "Melting Point Note"
    category = "Custom"
    description = "生成熔点记录备注，用于报告归档。"
    tags = ["demo", "thermal"]
    icon = "MP"

    input_ports = [
        Port("text", "Text", optional=True, description="附加说明"),
    ]
    output_ports = [
        Port("text", "Text", description="格式化后的备注"),
    ]
    parameters = [
        ParameterSpec("compound", "string", "", "化合物名称"),
        ParameterSpec("melting_point", "float", 0.0, "熔点 / °C", min=-273.15),
        ParameterSpec("note", "string", "", "额外备注"),
    ]

    def execute(self, inputs, ctx=None):
        compound = str(self.get_param("compound") or "unknown")
        mp = float(self.get_param("melting_point") or 0.0)
        note = str(self.get_param("note") or "")
        extra = ""
        upstream = inputs.get("text")
        if upstream is not None:
            extra = f" | upstream: {getattr(upstream, 'text', upstream)}"

        self.log(f"formatting melting point for {compound}")
        line = f"{compound}: mp = {mp:.1f} °C"
        if note:
            line += f" ({note})"
        line += extra
        return {"text": Text(text=line, language="zh")}
```

放进 `examples/plugins/`，设 `CHEMML_PLUGINS=examples/plugins`，然后：

```bash
python -m nodes.loader --query "Melting"     # 确认注册成功
```

## 2. 类属性契约

| 属性 | 必填 | 说明 |
| --- | --- | --- |
| `name` | ✅ | 画布上显示的名称，建议英文（前端可切换中英文，节点名保持稳定） |
| `category` | ✅ | 面板分组，如 `Analysis` / `Instruments` / `Custom` |
| `description` | ✅ | 一句话说明；写清科学用途 |
| `version` | — | 语义化版本。**不填即自动取平台版本**（来自 `chemml_version.VERSION`）；只有当节点需要独立于平台的版本号时才显式声明 |
| `tags` | — | 搜索关键词列表 |
| `icon` | — | 两个字母的角标，如 `"MP"` |
| `input_ports` | — | `Port` 列表，默认 `[]` |
| `output_ports` | — | `Port` 列表，默认 `[]` |
| `parameters` | — | `ParameterSpec` 列表，默认 `[]` |

## 3. `Port` — 端口

```python
Port(name, data_type="Any", description="", optional=False, multi=False)
```

- `data_type` 取 `DATA_TYPES` 之一；`Any` 接受任何输入。
- `optional=True`：允许不连线。此时 `inputs` 里**没有这个键**，用 `inputs.get("name")` 读取。
- `multi=True`：允许多条线连入，`inputs["name"]` 是**对象列表**。
- 端口名全小写、下划线分隔，且在工作流 JSON 的 `source_port`/`target_port` 中必须精确匹配（大小写不敏感）。

## 4. `ParameterSpec` — 参数

```python
ParameterSpec(name, type, default, description,
              options=None, min=None, max=None, required=False)
```

| type | 前端控件 | 强转规则 |
| --- | --- | --- |
| `string` / `text` | 输入框 / 多行 | `str()` |
| `integer` | 数字步进 | `int()`，受 `min/max` 约束 |
| `float` / `number` | 数字输入 | `float()`，受 `min/max` 约束 |
| `boolean` | 开关 | 真值判断 |
| `enum` | 下拉框 | `options` 为值列表或 `(value, label)` 元组列表；按 value 或 label 匹配 |
| `path` / `file` | 文件选择 | `str()`，相对于仓库根目录解析 |
| `molecule` / `material` | SMILES / 化学式输入 | 原样传字符串 |
| `list` / `dict` | JSON 编辑器 | `json.loads()` |

**枚举的正确写法**（中文标签 + 稳定值）：

```python
ParameterSpec(
    "method", "enum", "max", "归一化方法",
    options=[("max", "最大值"), ("area", "面积"), ("minmax", "Min-Max"), ("snv", "SNV")],
)
```

工作流 JSON 里写 `"method": "area"`，画布上显示"面积"。`(value, label)` 之外也接受裸字符串列表。

## 5. `execute()` 契约

```python
def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
```

- **输入**：`inputs` 的键是输入端口名；值是科学对象（`multi=True` 时是列表）。可选端口未连线时键不存在。
- **输出**：返回 dict，**键必须与 `output_ports` 的名字一一对应**。缺少端口 → 引擎报 `PortError`；多余键被忽略（但别这么做）。
- **异常**：抛任何异常都会让节点标记 `failed`、下游 `skipped`，运行继续。故意失败请抛 `NodeExecutionError` 并给出可读信息。
- **上下文**：`ctx` 提供 `ctx.artifact_path(filename)`（产物落盘）、`ctx.run_id`、`ctx.emit(...)`。

## 6. 常用工具

```python
self.log("message")                 # 日志 → 控制台 + WebSocket + events.jsonl
self.get_param("name")              # 读强转后的参数
self.get_param("name", default)     # 带默认值
ctx.artifact_path("plot.png")       # output/<run_id>/artifacts/plot.png
```

`nodes/_helpers.py` 里有一批转换助手，直接复用：

| 助手 | 作用 |
| --- | --- |
| `to_spectrum(obj)` / `to_molecule(obj)` / `to_material(obj)` | 容错转换：已是目标类型则原样返回，是 dict 则 `from_dict`，是字符串则按需解析 |
| `first_of(inputs, "port", required=False)` | 安全取单值，处理 `multi` 列表 |
| `build_material(formula, ...)` / `build_molecule(smiles, ...)` | 快速构造对象 |
| `write_artifact(path, content)` | 写产物并返回相对路径 |

## 7. 三种典型节点形态

**a. 纯计算节点**（无外部依赖，如 `NormalizeNode`）— 最常见，直接算、直接返回。

**b. 外部工具封装节点**（如 `ORCANode`）— 生成真实输入文件，尝试调用外部二进制，失败时回退内置引擎：

```python
def execute(self, inputs, ctx=None):
    engine = self._detect_engine()          # "orca" 或 None
    if engine:
        result = run_orca(...)              # 真实调用
        engine_name = "orca"
    else:
        result = builtin_eht(...)           # 内置回退
        engine_name = "builtin-eht"
    result.metadata["engine"] = engine_name # 永远标注来源
    self.log(f"solved with {engine_name}")
    return {"molecule": result}
```

**c. IO 节点**（如 `SpectrumFileNode`）— 唯一的文件边界，负责解析格式并构造科学对象。

## 8. 调试

```bash
# 单节点冒烟：只看你的节点
python scripts/smoke_nodes.py --filter MeltingPointNoteNode --traceback

# 查看注册规格（等价于 /api/nodes/{type}）
python -m nodes.loader --query "Melting" --json

# 进程内直接跑
python - <<'PY'
from chemml_sdk import load_nodes, create_node
load_nodes()
node = create_node("MeltingPointNoteNode", {"compound": "Caffeine", "melting_point": 235.0})
out = node.execute({})
print(out["text"].text)
PY
```

## 9. 测试你的节点

在 `scripts/smoke_nodes.py` 的 `make_*` 区补一组合成输入，让全量冒烟覆盖到它；复杂节点再加 pytest 用例到 `tests/test_nodes.py`。提交前确认：

```bash
pytest tests/test_nodes.py -q
python scripts/smoke_nodes.py --quiet        # 必须 77+/77+
```

## 10. 节点自检清单

- [ ] `execute()` 返回键与 `output_ports` 完全一致
- [ ] 可选端口用 `inputs.get()`，不假设键存在
- [ ] `multi=True` 端口按列表处理
- [ ] 参数默认值即可跑通（不填参数也能运行）
- [ ] 随机性有固定种子，同输入同输出
- [ ] 外部工具缺失时优雅降级并标注 `metadata["engine"]`
- [ ] 关键步骤有 `self.log()`
- [ ] docstring 写清科学原理、模型来源与近似程度
- [ ] `smoke_nodes.py` 覆盖通过
