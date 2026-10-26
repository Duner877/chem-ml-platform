# 贡献指南 / Contributing to Chem ML Platform

感谢你愿意为 Chem ML Platform 做贡献。仓库的基本要求是：**不含占位实现** —— 每个文件都必须能运行。请按下面的流程提交你的工作。

## 行为准则

尊重每一位贡献者。技术讨论对事不对人；涉及科学结论时必须给出可复现的依据（数据、代码路径、引用）。

## 提交 Issue

- **Bug**：附上最小复现步骤、Python/Node 版本、完整报错栈，以及 `python -m custom_nodes.loader --stats` 的输出（旧命令 `python -m nodes.loader --stats` 仍可用）。
- **功能请求**：说明科学场景（"我要用拉曼成像定位药物多晶型"），而不是只描述实现（"加一个 hyperspectral 节点"）。
- **节点请求**：给出输入/输出数据类型和关键参数，其余交给社区。

## 开发环境

```bash
git clone https://github.com/Duner877/chem-ml-platform.git
cd chem-ml-platform

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ./node_sdk/python          # 节点 SDK

# 跑通全部测试再动手
pytest -q
python scripts/smoke_nodes.py --quiet
python scripts/run_demo_workflows.py
```

## 分支与提交信息

- `main` 始终可发布；功能开发走 `feat/<topic>`，修复走 `fix/<topic>`，文档走 `docs/<topic>`。
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org/zh/v1.0.0/)：

```
feat(nodes): 新增 Raman Mapping 节点
fix(engine): 修复 enum 参数 (value,label) 元组强转失败
docs: 补充工作流 JSON 端口简写说明
test(engine): 覆盖 DAG 菱形并行执行
```

## 提交新节点（最常见的贡献）

1. 节点放 `nodes/<分类>/<节点名>.py`，一个文件一个节点，继承 `ScientificNode`，用 `@register_node` 装饰。
2. 在 `nodes/<分类>/__init__.py` 中导出，确保 `nodes.load_nodes()` 能发现它。
3. **必须提供冒烟覆盖**：在 `scripts/smoke_nodes.py` 中为该节点补一组合成输入（参考同类节点的写法）。
4. 节点自检清单：
   - [ ] `execute()` 返回的键与 `output_ports` 完全一致
   - [ ] 可选端口声明 `optional=True`，且 `execute()` 中不假设它一定存在
   - [ ] 参数都有合理默认值，默认参数即可跑通
   - [ ] 计算有固定随机种子（可复现）
   - [ ] 外部工具不可用时回退内置引擎，并在 `metadata["engine"]` 标注来源
   - [ ] 至少 3 条 `self.log()` 关键步骤日志
   - [ ] 文件头 docstring 写清科学原理与参考文献
5. 运行：

```bash
python -m custom_nodes.loader --query "<你的节点名>"    # 确认注册（等价的旧命令：python -m nodes.loader --query "..."）
pytest tests/test_nodes.py -q                    # 不破坏现有节点
python scripts/smoke_nodes.py --filter "<类名>"  # 新节点冒烟通过
```

## 代码风格

- **Python**：4 空格缩进；行宽 ≤ 100；类型注解用 `from __future__ import annotations`；docstring 用 Google 风格（Args/Returns/Raises）。
- **命名**：节点类 `<名称>Node`，端口/参数用小写下划线，常量全大写。
- **TypeScript**：2 空格缩进；组件用函数式 + hooks；类型放 `src/types.ts`。
- 不引入新的重量级依赖——新增依赖必须在 Issue 中先讨论。NumPy/SciPy/NetworkX/Pydantic 之外请慎重。

## 测试要求

| 改动范围 | 必须通过 |
| --- | --- |
| 引擎（`workflow_engine/`） | `pytest tests/test_engine.py` |
| 节点（`nodes/`、`models/`、`simulations/`） | `pytest tests/test_nodes.py` + `smoke_nodes.py` 全量 |
| 工作流（`workflows/`） | `pytest tests/test_workflows.py` + `run_demo_workflows.py` |
| 后端（`backend/`） | `pytest tests/`（含 API 测试） |
| 前端（`frontend/`） | `npm run lint` + `npm run build` |
| Node SDK | `cd node_sdk/nodejs && npm test` |

新增功能必须带测试。修 bug 必须先写一个能复现 bug 的失败测试。

## Pull Request

1. 标题用 Conventional Commits 格式。
2. 描述里写清：**做了什么 / 为什么 / 怎么验证的**（贴命令输出）。
3. PR 必须满足：`pytest` 全绿、`smoke_nodes.py` 77/77、`run_demo_workflows.py` 3/3、前端 `npm run build` 成功。
4. 一个 PR 只做一件事；拆不开的大改动先开 Issue 讨论设计。

## 科学严谨性

- 模拟节点（NMR/IR/XRD/MS…）必须在 docstring 中说明模型来源与近似程度；能对标真实实验趋势，不追求数值绝对一致。
- 数据库节点必须标注数据来源 URL 与许可；不允许把专有数据硬编码进仓库。
- LLM 相关节点必须支持离线回退，不允许"没有 API Key 就报错"。

## 许可证

提交即表示你的贡献按 [Apache License 2.0](LICENSE) 发布。
