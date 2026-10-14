# 示例

这里放**可直接运行的第三方节点示例**，用来演示怎么在不改平台源码的前提下扩展 Chem ML Platform。

```
examples/
└── plugins/
    └── melting_point_note.py    # 一个完整的自定义节点（熔点备注）
```

## 运行示例

```bash
# 1. 安装节点 SDK（一次性）
pip install -e ./node_sdk/python

# 2. 让平台发现这个插件并确认注册
CHEMML_PLUGINS=examples/plugins python -m nodes.loader --query "Melting"

# 3. 单独冒烟这个节点
CHEMML_PLUGINS=examples/plugins python scripts/smoke_nodes.py \
    --filter MeltingPointNoteNode --traceback

# 4. 或者起服务，在浏览器里拖出来用
CHEMML_PLUGINS=examples/plugins uvicorn backend.app:app --port 8000
```

节点会出现在左侧面板的 **Custom** 分类下。

## 示例里演示了什么

| 契约点 | 示例中的写法 |
| --- | --- |
| 注册 | `@register_node` 装饰器 |
| 可选输入端口 | `Port("text", "Text", optional=True)` + `inputs.get("text")` |
| 输出端口 | `return {"text": Text(...)}` 与 `output_ports` 一一对应 |
| 参数强转 | `float(self.get_param("melting_point"))`，`min=-273.15` 约束 |
| `multi=True` 的取值 | `isinstance(upstream, list)` 后取第一个 |
| 日志 | `self.log(...)` → 控制台 / WebSocket / `events.jsonl` |
| docstring | 写清科学原理，平台规范要求 |

## 把它接进工作流

```json
{
  "name": "熔点归档",
  "nodes": [
    { "id": "note", "type": "MeltingPointNoteNode",
      "params": { "compound": "Caffeine", "melting_point": 235.0, "note": "lit. 234-236" } }
  ],
  "edges": []
}
```

保存为 `my_workflow.json` 后：

```bash
python - <<'PY'
from chemml_sdk import ChemMLClient
client = ChemMLClient()
result = client.run({"name": "熔点归档",
                     "nodes": [{"id": "note", "type": "MeltingPointNoteNode",
                                "params": {"compound": "Caffeine",
                                           "melting_point": 235.0,
                                           "note": "lit. 234-236"}}],
                     "edges": []})
print(client.summary(result))
print(result["records"]["note"]["outputs"]["text"]["text"])
PY
```

预期输出：`Caffeine: mp = 235.0 °C (lit. 234-236)`。

## 写自己的插件

1. 复制 `melting_point_note.py`，改类名、端口、参数与 `execute()`。
2. 遵循 [docs/node-development.md](../docs/node-development.md) 的契约与自检清单。
3. 放进 `plugins/`（默认发现目录）或用 `CHEMML_PLUGINS` 指向任意目录。
4. 提交前跑 `python scripts/smoke_nodes.py --quiet` 确认全量通过。

> 注意：`CHEMML_PLUGINS` 目录下的每个 `.py` 都会被导入，请只放节点文件。
