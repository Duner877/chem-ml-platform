# Chem ML Platform v0.7.4 — 全量版项目说明书

> **作者**：Duner · **许可**：Apache-2.0 · **版本**：0.7.4（代号 Trusted Delivery Release）
> **编制时间**：2026-10-27 · **适用对象**：后续以 0.7.4 为蓝本继续开发的所有人

本文件是 0.7.4 的**单一入口文档**。它回答四个问题：这软件是什么、怎么组织的、代码怎么写、改完怎么验证。
文件结构、接口约定、命名规范与验证流程均以本文件为准；与代码不一致时，以代码为准并回来修本文件。

---

## 目录

1. [软件是什么](#1-软件是什么)
2. [仓库与目录结构](#2-仓库与目录结构)
3. [软件框架](#3-软件框架)
4. [节点系统规范](#4-节点系统规范)
5. [工作流格式规范](#5-工作流格式规范)
6. [代码规范](#6-代码规范)
7. [测试与质量门禁](#7-测试与质量门禁)
8. [发布与交付规范](#8-发布与交付规范)
9. [已知现状与遗留项](#9-已知现状与遗留项)
10. [常见任务速查](#10-常见任务速查)

---

## 1. 软件是什么

**Chem ML Platform** 是一个**节点化科学工作流平台**。它把四种东西缝在一起：

| 借鉴自 | 拿走什么 |
| --- | --- |
| **ComfyUI** | 图形化节点编排、插件式扩展、导入即注册 |
| **KNIME** | 数据处理流水线的分阶段结构 |
| **LabVIEW** | 仪器抽象层，把真实设备变成节点端口 |
| **AI Scientist** | 自主推理代理与科学假设验证 |

### 核心能力

- **101 个科学节点 / 30 个分类**，按设备类别分组（质谱、光谱、XPS、显微、衍射、热分析、地震反演……）
- **统一科学基座模型运行时**（`foundation/`）：`embed / similarity / predict / describe / catalog` 五个稳定 API
- **云 / 本地 AI 一键切换**（`ai_runtime/`）：9 家服务商的密钥管理，优先系统密钥环
- **全运行溯源**：每次运行产出 `provenance.json`，记录节点级溯源与资源快照
- **受控外部程序执行**（`simulations/controlled.py`）：白名单 + 显式 argv + 超时/并发限制
- **Electron 桌面外壳**（`desktop/`）：Windows 安装包 + 自动更新入口
- **质量门禁**（`scripts/quality_gate.py`）：27 个阶段，每阶段独立退出码与日志证据

### 一句话描述

> 拖拽节点、连成流水线、跑出带溯源的科学产物。

---

## 2. 仓库与目录结构

### 2.1 工作区布局（`Desktop/Chem ML Platform/`）

```
Chem ML Platform/
├── 01-源码/
│   ├── v0.7.4-active/              ← 唯一活跃源码仓库（git）
│   ├── Chem-ML-Platform-v0.7.4.zip ← 源码归档（可直接 push GitHub）
│   ├── Chem ML Platform Setup 0.7.4.exe ← NSIS 安装包
│   └── README-版本索引.md           ← 版本判断的唯一权威
├── 02-发布归档/                     ← 历史发布包与安装包归档
│   ├── 安装包/                      ← 0.7.2 / 0.7.3 / 0.7.4 安装包
│   ├── Chem-ML-Platform-v0.7.*.zip  ← 历史源码包
│   └── 评审包/                      ← 0.7.3 评审包
├── 03-需求与任务书/                 ← 各版本需求文档与任务书
├── 04-UI截图/                       ← 界面截图
├── 05-测试数据/                     ← mzML 样本与鉴定报告
├── 06-脚本与工具/                   ← 打包、同步、预发布检查脚本
├── 07-历史快照/                     ← git bundle 快照
├── Chem ML Platform/                ← 已安装程序（双击即用）
├── 固态DFT产物图/                   ← 铝晶胞案例产物
└── README-归档索引.md
```

### 2.2 源码仓库结构（`01-源码/v0.7.4-active/`）

```
v0.7.4-active/
├── chemml_version.py           ← 版本号权威来源（VERSION / CODENAME）
├── custom_nodes/               ← 【节点库】21 个设备分组，导入即注册
│   ├── _shared/                ← 跨设备共用工具
│   ├── mass_spectrometry/      ← 质谱
│   ├── spectroscopy/           ← 光谱
│   ├── surface_characterization/ ← XPS 等表面分析
│   ├── microscopy/             ← 显微
│   ├── diffraction/            ← 衍射
│   ├── thermal_analysis/       ← 热分析
│   ├── electrochemistry/       ← 电化学
│   ├── quantum_chemistry/      ← 量子化学
│   ├── molecular_dynamics/     ← 分子动力学
│   ├── materials_simulation/   ← 材料模拟
│   ├── battery_materials/      ← 电池材料
│   ├── foundation_models/      ← 科学基座模型
│   ├── seismic/                ← 地震反演
│   ├── ai_ml/                  ← LLM 调用
│   ├── agent/                  ← 自主代理
│   ├── analysis/               ← 通用分析
│   ├── data_io/                ← 数据读写
│   ├── databases/              ← 数据库查询
│   ├── gpu/                    ← GPU 加速
│   ├── questions/              ← 问答
│   └── reporting/              ← 报告生成
├── nodes/                      ← 旧路径兼容门面（指向 custom_nodes 同一模块对象）
├── workflow_engine/            ← 【引擎】DAG 调度、端口、注册表、错误模型
│   ├── engine.py               ← WorkflowEngine / ExecutionContext / RunResult
│   ├── node_base.py            ← ScientificNode 基类
│   ├── registry.py             ← NodeRegistry
│   ├── workflow.py             ← 工作流 JSON 解析与校验
│   ├── error_model.py          ← 14 个错误码 + 密钥脱敏
│   ├── events.py / cache.py / ports.py / objects.py
├── backend/                    ← 【后端】FastAPI
│   ├── app.py                  ← 应用装配
│   ├── security.py             ← 令牌、四类权限、审计日志
│   ├── ws_auth.py              ← WebSocket 握手判定
│   └── routers/                ← 13 个路由模块
├── frontend/                   ← 【前端】React + React Flow + Vite
│   └── src/{components,panels,nodes}/
├── desktop/                    ← 【桌面】Electron 外壳
│   ├── src/{main.js,preload.js,runtime-probe.js}
│   └── package.json
├── foundation/                 ← 科学基座模型运行时
├── ai_runtime/                 ← 云 / 本地 AI 切换、密钥管理
├── agent_runtime/              ← Agent 任务状态机、工具守卫
├── provenance/                 ← 溯源收集器
├── simulation_runtime/         ← 仿真后端（ABACUS 等外部引擎适配）
├── simulations/                ← 仿真领域逻辑
├── models/                     ← 领域模型
├── data_layer/ database_runtime/ storage/ databases/
├── node_sdk/{python,nodejs}    ← 第三方节点开发 SDK
├── node_registry/              ← 节点扫描器 + 生成目录
├── workflows/                  ← 11 个示例工作流 JSON
├── scripts/                    ← 门禁、打包、许可证、清单、基准
├── tests/                      ← 56 个测试文件
├── docs/                       ← 深度文档（架构 / 节点开发 / 任务书 / 报告）
├── config/ datasets/ models/ examples/
├── sbom.json NOTICE LICENSE    ← 合规三件套
└── docs/RELEASE_MANIFEST.json  ← 发布清单（产物摘要的权威）
```

### 2.3 三层架构

```
┌─────────────────────────────────────────────────────┐
│  桌面外壳 desktop/  (Electron)                        │
│  ├─ 主进程：窗口、更新检查、文件对话框                  │
│  └─ 预加载：安全桥接（contextBridge）                   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────────┐
│  前端 frontend/  (React + React Flow)                 │
│  ├─ 画布：节点拖拽连线、参数编辑                        │
│  ├─ 面板：数据目录、API Key、市场、更新、产物            │
│  └─ 主题：亮/暗，中文界面                              │
└──────────────────────┬──────────────────────────────┘
                       │ REST + WS
┌──────────────────────▼──────────────────────────────┐
│  后端 backend/  (FastAPI)                             │
│  ├─ routers/：nodes / workflows / runs / ws / agent …  │
│  ├─ security.py：会话令牌、四类权限、审计               │
│  └─ run_registry.py：运行订阅与所有权校验               │
└──────────────────────┬──────────────────────────────┘
                       │ 进程内调用
┌──────────────────────▼──────────────────────────────┐
│  引擎 workflow_engine/                                 │
│  ├─ WorkflowEngine：DAG 调度、并发、缓存、事件          │
│  ├─ NodeRegistry：类型注册与解析                       │
│  ├─ error_model.py：统一错误码 + 密钥脱敏              │
│  └─ ScientificNode：所有节点的基类                     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  节点库 custom_nodes/  (21 分组 / 101 节点)            │
│  ├─ 领域节点：质谱 / 光谱 / 电池 / 地震 …               │
│  ├─ 运行时：foundation / ai_runtime / agent_runtime     │
│  └─ 外部引擎适配：simulation_runtime（ABACUS 等）       │
└─────────────────────────────────────────────────────┘
```

---

## 3. 软件框架

### 3.1 引擎的运行模型

一次工作流运行（`RunResult`）由引擎产生，包含：

| 字段 | 含义 |
| --- | --- |
| `status` | `completed` / `failed` / `cancelled` |
| `node_records` | 每个节点的执行记录（`NodeExecutionRecord`） |
| `provenance_path` | `provenance.json` 路径（**溯源成功写入才有值**） |
| `artifacts` | 产物清单（报告、CSV、图片…） |

**执行上下文**（`ExecutionContext`）贯穿全程，提供工作目录、缓存、事件发射、参数访问。

**调度**：引擎按 DAG 拓扑序执行，无依赖关系的节点并行；菱形依赖（同一节点被两条路径汇合）只执行一次。

**缓存**：`use_cache` 开启时，相同输入 + 相同参数命中缓存，跳过重复计算。

### 3.2 错误模型

`workflow_engine/error_model.py` 定义了 **14 个错误码**，全部继承 `str, Enum`，可机器读：

```python
from workflow_engine.error_model import ErrorCode, PlatformError, from_exception

raise PlatformError(
    ErrorCode.NODE_INPUT_INVALID,
    "spectrum 数据缺少 mz 数组",
    details={"node": "MassSpectrumNode"},
)
```

**脱敏是强制的**：`redact_secrets()` 在错误进入日志/响应前抹掉密钥。任何新错误类型都必须走 `PlatformError`，不要裸抛异常——裸抛会绕过脱敏。

### 3.3 溯源

每次运行写一份 `provenance.json`，包含：

- 每个节点的**执行溯源**（`execution_mode`：native / external / simulated）
- **能力状态**（`capability_status`：implemented / executable / validated / experimental / unavailable）
- 依赖版本、资源快照、输入产物摘要

**诚实性契约**：写不出来就写不出来——`provenance_path` 为空是合法的，引擎不会伪造。

### 3.4 外部程序执行

`simulations/controlled.py` 是唯一允许拉起外部程序的地方：

- 可执行文件**白名单**（不含 shell 通配）
- **显式 argv**，禁止拼接 shell 字符串
- 独立工作目录
- 超时与并发上限

节点调用外部引擎后，必须在 `metadata["engine"]` 里标注真正应答的引擎（如 `external:abacus`）。外部工具不可用时回退内置引擎（`internal:tight-binding`），**不得报错终止**。

---

## 4. 节点系统规范

### 4.1 目录组织（ComfyUI 模式）

节点按**设备类别**分组，一个分组一个目录，一个节点一个文件：

```
custom_nodes/mass_spectrometry/
├── __init__.py
└── fragmentation.py        ← 一个文件一个节点
```

**发现机制**：`pkgutil.walk_packages` 递归遍历 → 导入模块 → `@register_node` 装饰器自注册。

> **加节点只需把文件放进对应目录**，不用改注册表，不用改加载器。

`nodes/` 是**兼容门面**：旧代码 `from nodes.instruments.ms import LCMSNode` 仍然可用，且两条路径指向**同一个模块对象**（源文件只执行一次——这条被回归测试锁住）。

### 4.2 节点编写规范

```python
"""节点文件头 docstring：写清科学原理、模型来源、参考文献。

节点自己的类 docstring 可声明 ``Author:`` 标签；不写则回落到项目作者 Duner。
"""

from __future__ import annotations

from typing import Any, Dict

from workflow_engine.node_base import ParameterSpec, ScientificNode, register_node


@register_node
class MyNode(ScientificNode):
    """一句话说明这个节点做什么。"""

    @classmethod
    def spec(cls) -> Dict[str, Any]:
        return {
            "name": "My Node",
            "name_zh": "我的节点",
            "category": "mass_spectrometry",
            "version": "0.7.4",
            "description": "做什么",
            "description_en": "What it does",
            "inputs": [
                {"name": "spectrum", "data_type": "Spectrum", "required": True},
            ],
            "outputs": [
                {"name": "result", "data_type": "Table"},
            ],
            "params": [
                ParameterSpec("threshold", float, 0.5, "阈值", "Threshold"),
            ],
        }

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = inputs["spectrum"]
        # 计算...
        return {"result": {"rows": [...]}}
```

**必检清单**：

- [ ] `execute()` 返回的键与 `outputs` 声明**完全一致**
- [ ] 可选端口声明 `"required": False`，且 `execute()` 中**不假设**它一定存在
- [ ] 每个参数都有合理默认值，**默认值即可跑通**
- [ ] 计算有**固定随机种子**（可复现）
- [ ] 外部工具不可用时回退内置引擎，并在 `metadata["engine"]` 标注来源
- [ ] 至少 3 条 `self.log()` 关键步骤日志
- [ ] 文件头 docstring 写清**科学原理与参考文献**
- [ ] `scripts/smoke_nodes.py` 里有对应的合成输入覆盖

### 4.3 端口数据类型

常见类型：`Spectrum` / `Table` / `Image` / `Curve` / `Document` / `Structure` / `Scalar` / `Vector`。
端口类型不匹配时引擎抛 `NodeInputError`，节点不需要自己检查。

**端口类型不一定是 `ScientificObject` 的子类。** `Survey`（地震采集对象）就是一个 3 维道集数组，
不是可渲染的科学对象，因此它在 `scripts/smoke_nodes.py` 的类型工厂表里没有通用条目。

冒烟脚本的合成输入按**端口类型**分发：`FACTORY[data_type]` 找不到就回退成 `make_spectrum()`。
所以新增一个非 `ScientificObject` 的端口类型时，必须同时在 `FACTORY` 里补一个工厂，
否则节点会收到一个 `Spectrum`，然后报「expects X but received Spectrum」——
看起来像节点坏了，其实是**夹具错了**。

还有一类更隐蔽的情况：同一个节点的多个端口必须**互相自洽**。
`SeismicSubmissionNode` 的 `velocity`（Image）要和 `survey` 的网格同形，
通用工厂给的 64×64 显微图和 survey 的 20×40 网格对不上，
节点会报 `operands could not be broadcast together`。
这类节点要用 `SHARED_FIXTURE_NODES` + `NODE_PORT_OVERRIDES`，
让所有端口从**同一份** fixture 派生，而不是各拿一个独立值。

### 4.4 能力与溯源声明

节点必须声明（通过类属性或 docstring 标签）：

| 声明项 | 取值 | 含义 |
| --- | --- | --- |
| `capability_status` | `implemented` / `executable` / `validated` / `experimental` / `unavailable` | 这个节点到什么程度可信 |
| `execution_mode` | `native` / `external` / `simulated` | 谁真正做的计算 |
| `reproducibility` | `deterministic` / `stochastic` / `conditional` | 同样的输入能否得到同样的输出 |
| `validation_evidence` | 文档路径或基准名 | 凭什么说它 validated |

**不允许夸大**：没有验证证据的节点只能说 `implemented`，不能说 `validated`。`node_registry/validator.py` 会检查这件事。

### 4.5 注册表是生成物

`node_registry/registry.json` 由扫描器生成，**不要手改**：

```bash
python -m node_registry --write     # 重新生成
python -m node_registry --stats     # 查看统计
python scripts/node_catalog.py --check   # 校验 README 与注册表一致
```

---

## 5. 工作流格式规范

工作流是 JSON，放在 `workflows/`。最小结构：

```json
{
  "name": "示例工作流",
  "author": "Duner",
  "version": "0.7.4",
  "nodes": [
    {
      "id": "n1",
      "type": "MassSpectrumNode",
      "params": {"threshold": 0.5},
      "position": {"x": 100, "y": 100}
    }
  ],
  "edges": [
    {"from": "n1", "from_port": "result", "to": "n2", "to_port": "spectrum"}
  ]
}
```

**约定**：

- `id` 在工作流内唯一
- `type` 必须是注册表里的节点类型名
- 边的 `from_port` / `to_port` 必须与节点端口声明匹配
- 端口支持简写（只写 `to` 时默认连第一个输出/输入）
- `author` 字段统一写 `Duner`

校验：

```bash
python -c "import json,pathlib; from workflow_engine.workflow import Workflow; \
  from nodes.loader import get_registry; \
  print(Workflow.from_dict(json.loads(pathlib.Path('workflows/XX.json').read_text())).validate(get_registry()))"
```

---

## 6. 代码规范

### 6.1 Python

| 项 | 规范 |
| --- | --- |
| 缩进 | 4 空格 |
| 行宽 | ≤ 100 |
| 类型注解 | 文件头 `from __future__ import annotations` |
| docstring | Google 风格（Args / Returns / Raises） |
| 导入 | 标准库 → 第三方 → 本地，三段空行分隔 |

**注释写"为什么"，不写"是什么"**。本仓库的注释密度偏高是有意的——大量注释解释的是**设计取舍的来由**，例如：

```python
# v0.7.4 fix: the comparison used to be byte-for-byte, which made the
# check unpassable on any machine but the one that generated the files.
# These artefacts record *installed* versions, and an installed version
# is a property of the environment, not of the release.
```

这种注释解释了**为什么不能那样写**——改代码时它比代码本身更重要。

### 6.2 命名

| 对象 | 规范 | 例 |
| --- | --- | --- |
| 节点类 | `<名称>Node` | `LCMSNode` |
| 端口 / 参数 | 小写下划线 | `spectrum`, `molecular_weight` |
| 常量 | 全大写 | `DEFAULT_AUTHOR` |
| 私有成员 | 前置下划线 | `_tracked_bytes` |
| 模块函数 | 动词开头 | `build_manifest`, `collect_records` |

### 6.3 TypeScript / React

- 2 空格缩进
- 函数式组件 + hooks
- 类型集中放 `src/types.ts`
- 主题色用 CSS 变量，不写死颜色

### 6.4 依赖策略

- **不引入新的重量级依赖**——新增依赖必须先讨论
- NumPy / SciPy / NetworkX / Pydantic 之外请慎重
- Python 依赖声明在 `requirements.txt`，锁定版本在 `requirements.lock`
- npm 依赖锁定在 `frontend/package-lock.json` / `desktop/package-lock.json`
- **锁定文件必须在 git 里**，不要手工改 lockfile（用 `npm install --package-lock-only` 重新生成）

> **平台专用二进制包不要写成直接依赖。**
> `@esbuild/win32-x64`、`@rollup/rollup-win32-x64-msvc` 这类包是 esbuild / rollup
> 自己的 `optionalDependencies`，npm 会按当前平台自动挑选。
> 把某一个平台变体提为直接依赖，会让 `npm ci` 在**其它平台直接失败**——
> CI 报的是 `EBADPLATFORM: Unsupported platform for @esbuild/win32-x64`。
> 需要加平台包时，用 `optionalDependencies` 而不是 `dependencies` / `devDependencies`。

> **lockfile 必须包含所有平台的变体，否则换台机器就装不上。**
>
> 这条比上一条更隐蔽。npm 生成的 `lockfileVersion: 3` lockfile，
> `packages` 段里**只记录生成它的那台机器对应的平台变体**——
> 在 Windows 上生成，就只有 `@rollup/rollup-win32-x64-msvc`，
> 没有 `@rollup/rollup-linux-x64-gnu`。
> 于是 `npm ci` 在 Linux 上会装不全，报的是
> `Cannot find module '@rollup/rollup-linux-x64-gnu'`，
> 而这条错误**不指向 lockfile**，看着像 vite 的问题。
>
> 正确做法是生成**全平台** lockfile：
>
> ```bash
> cd frontend
> npm install --package-lock-only --ignore-scripts --no-audit --no-fund --os --cpu
> ```
>
> `--os --cpu` 不带值，表示「不按当前平台过滤」，npm 会把所有平台变体都写进 lockfile。
> 生成后应当看到 **34 个**含平台名的条目（esbuild 25 个 + rollup 22 个，去重后），
> 而不是只有 2 个。**改完必须在两个平台上各验证一次 `npm ci`**——
> 只在 Windows 上验证，等于没验证。

### 6.5 错误处理

- 节点内部**不要裸抛异常**，用 `PlatformError` + `ErrorCode`
- 可预期的失败（如外部工具缺失）应回退并标注，不是报错
- 密钥永远不要进日志——`redact_secrets()` 会处理，但不要绕过它

### 6.6 Git 约定

- `main` 始终可发布
- 分支：`feat/<topic>` / `fix/<topic>` / `docs/<topic>`
- 提交信息遵循 **Conventional Commits**：

```
feat(nodes): 新增 Raman Mapping 节点
fix(engine): 修复 enum 参数 (value,label) 元组强转失败
docs: 补充工作流 JSON 端口简写说明
test(engine): 覆盖 DAG 菱形并行执行
```

- 提交信息用**中文正文**说明「做了什么 / 为什么 / 怎么验证的」
- **修 bug 必须先写一个能复现的失败测试**
- **不要用 `--no-verify` 绕过钩子**

### 6.7 行尾规范

`.gitattributes` 统一 `* text=auto eol=lf`：仓库内一律 **LF** 入库。
Windows 工作区看到 CRLF 是 checkout 行为，**不要**为此改文件。

> 涉及摘要/哈希的计算，必须模拟 git 的 clean filter（二进制原样存、文本 CRLF→LF），
> 否则同一份代码在不同机器上会算出不同摘要。参考 `scripts/release_manifest.py`
> 的 `_git_stored_bytes()`。

---

## 7. 测试与质量门禁

### 7.1 测试布局

56 个测试文件，标记分类（`pytest.ini`）：

| 标记 | 范围 | CI job |
| --- | --- | --- |
| `unit` | 单元测试 | job 3 |
| `integration` | 集成测试 | job 4 |
| `security` | 安全测试 | job 5 |
| `benchmark` | 基准测试 | job 6 |
| `desktop` | 桌面端 | job 2（静态 job 内） |
| `requires_env` | 依赖宿主环境的测试 | 全部跳过时记 SKIP |

```bash
pytest -q -m unit
pytest -q                          # 全量
pytest tests/test_engine.py -q    # 单文件
```

### 7.2 质量门禁

```bash
python scripts/quality_gate.py --fast    # 跳过前端构建与安装包构建
python scripts/quality_gate.py           # 全量
```

**27 个阶段**，每个阶段独立退出码、独立日志、独立证据：

| 阶段组 | 阶段 |
| --- | --- |
| static | python_compile · node_registry_schemas · node_registry_provenance · node_catalog_readme_sync · workflow_json_validation · docs_mojibake_scan · credential_scan |
| unit | unit_tests |
| integration | integration_tests · demo_workflows_dry_run · reproducibility_verification |
| security | security_tests |
| benchmark | benchmark_tests · synthetic_benchmark |
| build | frontend_typescript · frontend_production_build · electron_build_config · electron_installer_artefact |
| desktop | desktop_runtime_probe · desktop_tests |
| compliance | version_consistency · release_manifest · dependency_licenses · license_sbom_report · release_cleanliness |
| environment | host_dependent_tests · host_gpu_status |

**状态词汇是封闭的**：`PASS` / `FAIL` / `TIMEOUT` / `SKIP` / `ERROR`。
**TIMEOUT 永远是失败**，绝不折叠成 PASS。SKIP 从不算通过，但必须给出理由。

产物写在 `output/`：
- `output/quality_gate.json` — 机器可读
- `output/quality_gate.md` — 人读报告
- `output/gate_logs/*.log` — 每阶段完整 stdout+stderr

### 7.3 附加验证脚本

```bash
python scripts/smoke_nodes.py --quiet          # 节点冒烟
python scripts/run_demo_workflows.py           # 11 个示例工作流
python scripts/benchmark_lcms.py --strict      # LC-MS 已知答案基准
python scripts/verify_reproducibility.py --repeat 2   # 两次运行逐节点比对
python scripts/version.py --check              # 三处版本号一致
python scripts/release_manifest.py --check    # 发布清单与树一致
python scripts/license_report.py --check       # 许可证/SBOM 与依赖一致
python scripts/node_catalog.py --check         # README 节点目录与注册表一致
```

### 7.4 CI 流水线

`.github/workflows/ci.yml`，**10 个 job**（编号 1、3、4、5、6、7/8、9、10、11、12），
**用 `needs:` 串成依赖链**——任一前置失败，下游全部 `skipped`：

```
1 static ──┬─→ 3 unit ──┐
           ├─→ 4 integration ──┐
           ├─→ 5 security ──┤
           ├─→ 6 benchmark ──┤
           ├─→ 9 frontend build ──┤
           ├─→ 7,8 licence + SBOM ──┤
           └─→ 12 release manifest ──┴─→ 10 installer ─→ 11 clean-env E2E
```

**重要**：CI 与本地**必须跑同一份代码**。门禁实现住在 `scripts/quality_gate.py`，
CI 用 `python scripts/quality_gate.py --fast` 调用它，而不是在 workflow 里另写一套逻辑。

### 7.5 测试的副作用纪律

**测试不得写入仓库的真实产物。**

这条纪律是踩过坑的：`tests/test_v07_1_license_report.py` 早期直接对仓库里的
`sbom.json` / `NOTICE` / `THIRD_PARTY_LICENSES.md` 调 `--write`，
CI 上 pytest 先跑、清单阶段后跑，于是清单比对的字节已经被测试改过，
每次 CI 都报「清单漂移」——而本地永远复现不出来（本地工作区是 CRLF，
走归一化后摘要碰巧一致）。

**正确做法**：需要写盘时写到临时目录。

```python
lic.main(["--write", "--out-dir", str(tmp_path / "out")])
```

仓库里另有一条回归测试 `test_writing_does_not_touch_the_repository` 盯着这件事。

### 7.6 派生产物必须跟随源变更

**改了锁文件，就必须重新生成派生产物。**

前端 `package-lock.json` 一改，下列三样东西立刻过期：

| 产物 | 生成命令 |
| --- | --- |
| `sbom.json`、`docs/THIRD_PARTY_LICENSES.md` | `python scripts/license_report.py --write` |
| `docs/RELEASE_MANIFEST.json`、`docs/RELEASE_MANIFEST.md`、`SHA256SUMS` | `python scripts/release_manifest.py` |

漏掉任何一样，CI 的 `license_sbom_report` 与 `release_manifest` 两个阶段就会报
「stale」/「drifted」——而且报的是**依赖摘要对不上**，不告诉你是哪个改动引起的，
排查起来很绕。**改依赖 → 重生成 → 再提交**，这三步要一起做。

### 7.7 测试的断言口径

**断言要验证性质，不要验证巧合。**

`tests/test_v07_4_release_manifest.py` 里有一条测试，它断言「模块算出的摘要」
等于「`git cat-file -p HEAD:sbom.json` 的内容」。

这个断言在**工作区干净**时成立，在工作区刚改过产物时不成立——
于是每次重新生成 `sbom.json` 之后，这条测试都会失败一次，
而它其实并没有发现任何问题：它真正要验证的性质是
「本模块实现的 clean filter 与 git 的 clean filter 对同一文件给出相同字节」。

现在的写法是与 git 自己比：

```python
ours = subprocess.run(["git", "hash-object", "--stdin"], input=blob, ...)
git  = subprocess.run(["git", "hash-object", "--path=sbom.json", "sbom.json"], ...)
assert ours.stdout == git.stdout
```

这个断言在任何工作区状态下都成立，而且语义更准。
（干净 clone 里两种口径等价，已验证。）

> **通用教训**：当一条测试「只在特定状态下通过」时，先问它是不是把状态当成了性质。
> 换一种与状态无关的比法，往往既能测到真正的东西，又不会在正常工作中假报警。

---

## 8. 发布与交付规范

### 8.1 版本号铁律

**三处必须一致**：

| 文件 | 字段 |
| --- | --- |
| `chemml_version.py` | `VERSION = "0.7.4"` |
| `frontend/package.json` | `"version": "0.7.4"` |
| `desktop/package.json` | `"version": "0.7.4"` |

`python scripts/version.py --check` 会校验，不一致退出码 1。

> **目录名不是版本依据**。历史上目录名长期落后于内部版本，曾导致「按目录名选中完全错误的版本」。
> 判断版本一律读 `chemml_version.py`。

### 8.2 合规三件套

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `LICENSE` | 手写 | Apache-2.0 全文 + 附录署名 `Copyright 2026 Duner` |
| `NOTICE` | `license_report.py --write` | 分发组件归属声明 |
| `sbom.json` | `license_report.py --write` | CycloneDX 1.5 物料清单 |
| `docs/THIRD_PARTY_LICENSES.md` | `license_report.py --write` | 人读版许可证清单 |
| `docs/PROVENANCE.md` | 手写 | 来源、许可、贡献归属 |

**署名统一为 `Duner`**。版权持有人是**姓名**，GitHub **账号**是 `Duner877`——
后者出现在 clone URL 与自动更新的仓库定位里，改了会失效，两者刻意分开。

`license_report.py --check` 与 `--write` 的分工：

- `--check`：**只读**，比对磁盘上的产物与「按当前依赖应生成的内容」，有漂移退出码 1
- `--write`：重新生成三个产物文件

**`--check` 永远不写盘**——一个会「修复」自己要检查的文件的检查，检测不出任何东西。

### 8.3 发布清单

`docs/RELEASE_MANIFEST.json` 记录每个发布产物的 sha256、大小、产出方式。

**清单描述的是「将要提交的那一版树」**，不是 `HEAD`——因为清单与它描述的产物在同一个提交里，
读 `HEAD:` 会记录上一版的字节，`--check` 必然报漂移。

实现方式：读工作区文件，套用 git 的 clean filter（二进制原样存、文本 CRLF→LF），
这样算出的摘要与仓库实际存储的 blob 一致，跨机器必然相同。

清单里排除两类产物（`_COMPARABLE_ARTEFACTS`）：

- 源码归档（在仓库外）
- 安装包（在 gitignored 的构建目录里）

因为它们**不在 checkout 里**，比的是「这台机器的构建残留」对「树」，是噪声不是信号。

### 8.4 打包

```bash
python scripts/package.py              # 源码归档
cd desktop && npm run build             # 安装包（NSIS）
```

打包器是「什么该进包」的权威（`package.py` 的 `should_skip()`）——
缓存、密钥、运行时数据、`node_modules` 都不进包。

### 8.5 交付清单

一次完整交付包含：

| 交付物 | 位置 |
| --- | --- |
| 源码仓库 | `01-源码/v0.7.4-active/`（git） |
| 源码归档 | `01-源码/Chem-ML-Platform-v0.7.4.zip` |
| Windows 安装包 | `01-源码/Chem ML Platform Setup 0.7.4.exe` |
| 产物摘要 | 仓库内 `SHA256SUMS` |
| 发布清单 | 仓库内 `docs/RELEASE_MANIFEST.{json,md}` |

精确字节数与 SHA-256 **以仓库里的 `SHA256SUMS` 为准**——NSIS 每次打包会嵌时间戳，
字节数有几十字节浮动，记文件才不会记下必错的数字。

---

## 9. 已知现状与遗留项

如实记录，不掩饰：

| 项 | 现状 | 影响 |
| --- | --- | --- |
| 桌面已安装程序 | `Chem ML Platform/` 目录里是**已安装版**，内容停留在更早的 commit `01e9665` | 重新运行安装包即可升级到当前 commit |
| `desktop/dist/` | 已用当前 commit `cdae1b5` 重建：`Chem ML Platform Setup 0.7.4.exe`（79 MB）+ `win-unpacked/`（262 MB） | 无。`BUILD_INFO.json` 记录 `dirty: false` |
| 冒烟测试覆盖 | 新增节点时**必须**补 `scripts/smoke_nodes.py` 覆盖，否则门禁不会发现 | 纪律问题，靠 review 保证 |
| npm audit | `npm install` 报 3 个漏洞（2 moderate / 1 high），来自前端依赖树 | 未处理。升级需评估 React 18 / Vite 5 的兼容性 |

---

## 10. 常见任务速查

### 改代码

```bash
cd "C:/Users/hanku/Desktop/Chem ML Platform/01-源码/v0.7.4-active"
git status -sb
```

### 加一个节点

1. 建文件 `custom_nodes/<设备分组>/<节点名>.py`
2. 继承 `ScientificNode`，加 `@register_node`
3. 在 `spec()` 里声明 name / category / inputs / outputs / params
4. 实现 `execute()`，返回键与 outputs 一致
5. 在 `scripts/smoke_nodes.py` 补合成输入
6. 验证：

```bash
python -m custom_nodes.loader --query "<节点名>"
python scripts/smoke_nodes.py --filter "<类名>"
python -m node_registry --write          # 重新生成注册表
python scripts/node_catalog.py --check    # 同步 README 目录
pytest -q
```

### 跑完整门禁

```bash
python scripts/quality_gate.py --fast
```

### 提交并推送

```bash
git add -A
git commit -F - <<'EOF'
feat(nodes): <做了什么>

<为什么>

<怎么验证的 —— 贴命令输出>
EOF
git push origin main
```

### 重新生成全部合规产物

```bash
python scripts/license_report.py --write   # NOTICE / sbom / THIRD_PARTY_LICENSES
python scripts/release_manifest.py         # 发布清单 + SHA256SUMS
python scripts/version.py --check          # 三处版本号
```

### 构建安装包

```bash
cd desktop
npm ci                                   # 或 npm install
npm run build                            # 产出 dist/Chem ML Platform Setup <版本>.exe
```

---

## 附：关键约定速查卡

```
节点类名        <名称>Node
节点目录        custom_nodes/<设备分组>/<节点名>.py
端口/参数名     小写下划线
常量            全大写
节点发现        pkgutil.walk_packages + @register_node
节点基类        ScientificNode
错误类型        PlatformError + ErrorCode（不要裸抛）
外部程序        只经 simulations/controlled.py
行尾            LF 入库（.gitattributes）
版本三处        chemml_version.py / frontend/package.json / desktop/package.json
版权署名        Duner（GitHub 账号 Duner877）
提交信息        Conventional Commits，中文正文
分支            feat/ fix/ docs/
测试副作用      不得写入仓库真实产物
门禁状态        PASS/FAIL/TIMEOUT/SKIP/ERROR，TIMEOUT 永远失败
CI 与本地       必须跑同一份 quality_gate.py
```

---

*本说明书随代码演进。改了架构、改了规范、改了流程，回来改这份文件。*
