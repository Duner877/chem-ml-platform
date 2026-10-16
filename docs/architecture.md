# 架构

Chem ML Platform v0.7.1 是一个**四层架构**：编辑层（前端）→ 服务层（FastAPI）→ 引擎层（工作流引擎）→ 计算层（节点与模型）。层与层之间只通过稳定契约通信，任何一层都可以单独替换。v0.6 在计算层旁新增了一个**统一运行时层**（`foundation/` `ai_runtime/` `database_runtime/` `simulation_runtime/` `data_layer/` `report_agent/`），把基座模型、AI、数据库、仿真、数据目录与报告收敛为稳定门面，节点只做薄适配。

```
┌──────────────────────────────────────────────────────────────────────┐
│  编辑层  frontend/          React 18 + TypeScript + React Flow        │
│  三栏 ComfyUI 式编辑器 + 选项卡工作台 Dock（检查器│AI│Agent│数据│仿真）  │
└───────────────┬──────────────────────────────────────────────────────┘
                │ REST (/api/*) + WebSocket (/api/ws/run/{id})
┌───────────────▼──────────────────────────────────────────────────────┐
│  服务层  backend/           FastAPI + Pydantic                         │
│  routers/ nodes · workflows · runs · ws · ai · agent · data ·          │
│           simulations · foundation                                     │
│  节点目录 │ 工作流 CRUD/校验/执行 │ 运行历史 │ 产物下载 │ 实时事件       │
└───────────────┬──────────────────────────────────────────────────────┘
                │ Python 进程内调用
┌───────────────▼──────────────────────────────────────────────────────┐
│  引擎层  workflow_engine/                                              │
│  node_base(ScientificNode/ParameterSpec) · ports · registry · engine  │
│  workflow(校验) · events(EventBus) · cache(ResultCache) · objects     │
│  parsers(mzML/mzXML/MGF/MSP/JCAMP/XY/Bruker) · processing             │
└───────────────┬──────────────────────────────────────────────────────┘
                │ @register_node 注册，execute() 调用
┌───────────────▼──────────────────────────────────────────────────────┐
│  计算层  nodes/ + models/ + simulations/ + databases/                 │
│  89 个科学节点 │ SMILES/描述符/指纹 │ EHT/LJ-MD │ 本地分子库/材料库     │
│  ─────────────────────────────────────────────────────────────────   │
│  统一运行时层（v0.6）                                                  │
│  foundation/ 基座模型注册表（embed/similarity/predict/describe/catalog）│
│  ai_runtime/(Cloud⇄Local) · database_runtime/ · simulation_runtime/(作业)│
│  data_layer/(可检索目录) · report_agent/(MD/HTML/PDF) · node_registry/  │
└──────────────────────────────────────────────────────────────────────┘
```

## 1. 引擎层详解

### 1.1 `ScientificNode` 基类（`node_base.py`）

每个节点是一个 Python 类，声明式地描述自己的接口：

```python
@register_node
class SavgolNode(ScientificNode):
    name = "Savitzky-Golay Smoothing"
    category = "Analysis"
    description = "..."
    version = "1.0.0"
    tags = ["spectrum", "smoothing"]

    input_ports  = [Port("spectrum", "Spectrum")]
    output_ports = [Port("spectrum", "Spectrum")]
    parameters   = [ParameterSpec("window", "integer", 11, "窗口宽度", min=5, max=101)]

    def execute(self, inputs, ctx=None): ...
```

引擎在实例化时把 `parameters` 的默认值与工作流 JSON 中的覆盖值合并，`get_param()` 读到的永远是强转后的值。

### 1.2 注册表（`registry.py`）

`NodeRegistry` 是全局单例，按类名索引，支持别名：

- `register(cls)` — 由 `@register_node` 调用；类名重复会抛出 `NodeNotFoundError` 系列的注册错误。
- `resolve(type_name)` — 类名 → 类；找不到时尝试别名，再找不到抛 `NodeNotFoundError`。
- `create(type_name, params)` — 直接实例化。
- `types()` / `categories()` — 供 `/api/nodes` 与前端面板使用。
- `discover_package("nodes")` — 递归导入 `nodes/` 下所有模块（内置 89 个节点的入口）。
- `discover_plugins(directory)` — 导入插件目录下所有 `*.py`（第三方节点入口，读取 `CHEMML_PLUGINS`）。

`nodes/loader.py` 是唯一入口：`load_nodes()` 先 `discover_package` 再 `discover_plugins`，保证幂等。

### 1.3 端口与类型兼容（`ports.py`）

```python
DATA_TYPES = ("Any", "Spectrum", "Molecule", "Material", "Table",
              "Image", "SpectralMatch", "Reaction", "Text", "ScientificReport")

_IMPLICIT_CASTS = {
    "ScientificReport": ("Text",),   # 报告可直接当文本用
    "Molecule":         ("Text",),
    "Material":         ("Text",),
}
```

`types_compatible(source, target)`：任一端为 `Any` 即通配；否则要求同类型或命中隐式转换表。连线在校验期检查，运行期不再检查——非法连线根本跑不起来。

### 1.4 执行引擎（`engine.py`）

```
run(workflow)
  │
  ├─ assert_valid()              # 结构校验，失败抛 WorkflowValidationError
  ├─ ExecutionContext            # run_id / 工作目录 / EventBus / ResultCache
  │
  ├─ for generation in nx.topological_generations(graph):   # 按代
  │     ├─ 单节点 or max_workers==1  →  串行执行
  │     └─ 多节点                   →  ThreadPoolExecutor 并行
  │           └─ _execute_node()
  │                 ├─ 缓存命中？    → NODE_CACHED，直接复用
  │                 ├─ 组装 inputs（按端口名取上游输出）
  │                 ├─ node.execute(inputs, ctx)
  │                 ├─ 记录 NodeExecutionRecord（状态/时长/日志）
  │                 └─ 产物登记到 ctx.artifacts
  │
  └─ RunResult                   # status / records / artifacts / duration_ms
```

**失败隔离**：任一节点抛异常，该节点标记 `failed`，所有下游节点标记 `skipped`，其余分支继续跑完——你不会因为一个分支失败丢掉整个工作流的结果。

**并行语义**：同一"代"内的节点彼此无数据依赖，可乱序完成；跨代严格有序。`max_workers` 默认 4。

**外部输入注入**：`run(workflow, inputs={node_id: {port: value}})` 可以把 JSON 可序列化的值直接注入指定节点端口，用于把平台嵌进更大系统。

### 1.5 事件总线（`events.py`）

`EventBus` 是同步发布/订阅。引擎在执行过程中发布 9 类事件：

| 事件 | 时机 |
| --- | --- |
| `run_started` / `run_completed` / `run_failed` | 运行开始 / 成功结束 / 失败结束 |
| `node_started` | 节点开始执行 |
| `node_log` | 节点调用 `self.log()` 或进度更新 |
| `node_completed` / `node_failed` / `node_skipped` | 节点终态 |
| `node_cached` | 命中结果缓存 |

后端 `routers/ws.py` 把事件总线桥接到 WebSocket；SDK 的 `stream(run_id)` 消费同一条流。事件同时落盘到 `output/<run_id>/events.jsonl`，可通过 `GET /api/workflows/runs/{id}/events` 回放。

### 1.6 结果缓存（`cache.py`）

`ResultCache` 以 `sha1(节点类型 + 参数 + 输入对象序列化)` 为键，把节点输出存到 `output/<run_id>/cache/`。默认关闭（`use_cache=False`），因为科学计算要求可复现优先于省时间；开启后重复运行同一工作流会命中 `node_cached`。

## 2. 科学对象协议（`objects.py`）

全部基于 Pydantic v2，全部可 `to_dict()` / `from_dict()`，全部可 JSON 序列化——这就是工作流能在 HTTP 上跑起来的原因。

| 对象 | 关键字段 | 典型生产者 |
| --- | --- | --- |
| `Spectrum` | `peaks: [Peak(x, y)]`、`axis`、`technique`、`metadata` | 仪器节点、文件解析器 |
| `Molecule` | `smiles`、`atoms`、`bonds`、`properties` | SMILES 输入、数据库检索 |
| `Material` | `formula`、`structure: CrystalStructure`、`properties` | 材料输入、XRD |
| `Table` | `columns`、`rows` | CSV 读取、汇总表 |
| `Image` | `width/height`、`data`（base64）、`colormap` | 成像类节点 |
| `SpectralMatch` | `query`、`candidates: [{score, molecule}]` | 相似性检索 |
| `Reaction` | `reactants`、`products`、`conditions` | 反应输入 |
| `Text` | `text`、`language` | LLM、文本输入 |
| `ScientificReport` | `title`、`sections`、`artifacts` | 报告构建 |

**约定**：节点把来源信息写进 `metadata`（如 `engine: "orca-5.0"` vs `engine: "builtin-eht"`），下游与报告据此标注数据可信度。

## 3. 目录职责

| 目录 | 职责 | 能否单独测试 |
| --- | --- | --- |
| `workflow_engine/` | 引擎原语，不 import `nodes/` | ✅ `pytest tests/test_engine.py` |
| `nodes/` | 89 个科学节点，按分类分目录 | ✅ `scripts/smoke_nodes.py` |
| `models/` | 纯计算：SMILES、描述符、指纹、几何、谱学 | ✅ 单元测试 |
| `simulations/` | EHT、紧束缚、LJ-MD、外部程序封装 | ✅ 单元测试 |
| `databases/` | 本地分子库与材料库数据 + 加载器 | ✅ |
| `workflow_engine/parsers/` | 7 种谱图格式解析 | ✅ |
| `foundation/` | 统一科学基座模型注册表（v0.6） | ✅ `pytest tests/test_v06.py` |
| `ai_runtime/` | LLM/多模态运行时 + Cloud/Local 切换（v0.6） | ✅ |
| `data_layer/` | 科学数据层与可检索目录（v0.6） | ✅ |
| `simulation_runtime/` | 四段式仿真运行时 + 作业管理器（v0.6） | ✅ |
| `database_runtime/` | 统一数据库检索运行时 | ✅ |
| `report_agent/` | MD/HTML/PDF 报告代理 | ✅ |
| `node_registry/` | 节点注册中心服务，导出 `registry.json` | ✅ `python -m node_registry --write` |
| `backend/` | HTTP 边界，只做协议转换 | ✅ TestClient |
| `frontend/` | 编辑层 | ✅ `npm run build` |
| `node_sdk/` | 对外 SDK | ✅ `pytest` + `npm test` |

**依赖方向永远是向下的**：`nodes/` 可以 import `workflow_engine/`，`workflow_engine/` 永远不 import `nodes/`。这条规则让你可以在不启动平台的情况下单独测试引擎。

## 4. 一次运行的完整生命周期

```
POST /api/workflows/01_....json/run
  │
  ├─ routers/workflows.py        读取 workflows/01_....json
  ├─ WorkflowEngine.run()        校验 → 建 ExecutionContext
  │     └─ 事件同时写入内存总线 + output/<run_id>/events.jsonl
  ├─ 逐代执行，节点产物写入 output/<run_id>/artifacts/
  └─ RunResponse                 {run_id, status, records, artifacts, duration_ms}
        │
        ├─ 前端通过 /api/ws/run/{run_id} 实时看到日志
        └─ GET /api/runs/artifacts/<path> 下载 CSV/HTML/报告
```

## 5. 统一运行时层（v0.6）

v0.6 把所有"外部能力"收敛为**门面 + 注册表 + 诚实降级**三件套，节点退化为薄适配器。

### 5.1 科学基座模型 `foundation/`

一个注册表（`FoundationRegistry`）+ 五个稳定 API：`embed / similarity / predict / describe / catalog`。

| 家族 | 模型 | 维度 | 能力 |
| --- | --- | --- | --- |
| molecular | ChemBERTa · GROVER · Graphormer · Uni-Mol | 384 / 512 / 768 / 512 | `embed` |
| molecular | Morgan · Descriptor-Vector | 2048 / 18 | `embed` |
| property | Physchem | — | `predict` |
| spectral | Spectrum-Bin · Spectrum-Summary | 128 / 8 | `embed` |

无权重时使用确定性 `seed_vector`（同输入同输出）；`requires_weights` 标明哪些模型在提供权重后可切真实推理。**绝不返回随机结果。**

### 5.2 Cloud / Local 切换 `ai_runtime/config.py`

`mode ∈ {auto, cloud, local, open_source, chemistry, offline}`，持久化 `config/ai.json`，环境变量 `CHEMML_AI_MODE` 覆盖。`family_order()` 始终把 `offline` 追加末位——**任何模式下功能不中断**，只改变数据来源。

### 5.3 数据目录 `data_layer/catalog.py`

`DataCatalog` 为分子（morgan）与谱图（spectrum-bin）生成基座嵌入，支持跨类型相似检索；`get_catalog(path=None)` 路径感知并带缓存，`CHEMML_CATALOG` 可重定向。

### 5.4 仿真作业 `simulation_runtime/jobs.py`

`JobManager`（线程池）包装 `runtime.run(family, system, backend)`，提供 `submit / run_now / list / get / stats`，`SimulationJob` 记录状态、结果与来源引擎。

### 5.5 凭据存储 `ai_runtime/credentials.py`（v0.7.3）

与 `ai_runtime/config.py` 分工明确：config 管**行为**（模式、供应商、模型），credentials 管**密钥**。存储顺序为**系统密钥环 → 本地文件**（`config/credentials.json`，已 gitignore，权限 600）。

写入时同步推入 `os.environ`：供应商读的是环境变量，只落盘会让界面显示「已配置」而运行时仍在离线降级。

**没有密钥环时必须落盘**。文件回退的判据是「keyring 是否可用」，而不是「keyring 写入是否成功」——后者只在装了密钥环的机器上成立，而**没有密钥环正是桌面版的常态**。判据写错时密钥只活在当前进程：界面显示已配置、告警文案宣称密钥在 `config/credentials.json`（该文件并不存在）、重启即丢、运行时静默离线。

**删除只清除本进程写入的变量**。继承自 shell 的 `OPENAI_API_KEY` 不属于本平台，删掉它无法恢复，因此在 `shell_env_preserved` 中如实报告——否则「已删除」会被理解成「该服务商不可用」，而它其实还能用。

任何响应都不含明文：`mask_secret()` 保留首尾各 4 字符，≤ 8 字符全掩。没有「显示明文」按钮，因为后端根本不发送。供应商错误文本同样是第三方内容，会原样引用用户提交的密钥，因此返回前统一脱敏（401/403/404/429 本就不回显原文，兜底分支也必须如此）。

### 5.6 Agent 工具守卫 `agent_runtime/tool_guard.py`（v0.7.3）

借鉴腾讯开源 [Octop](https://github.com/TencentCloud/Octop) 的 `tool_guard`。核心是**一个判定点**：任何入口（Agent 节点、`/api/agent/*`、工作流运行）在执行**之前**都要过 `check_tool_call()`，而不是事后补一条日志。

```
ToolCall(node_type, approved?)
      │
      ▼
  ToolGuard.check()          首条匹配胜出；无匹配 → deny
      │
   ┌──┴──┬────────┐
allow  approval  deny
                │
        approved=True 才放行
```

判定分三档而非布尔值：读与删不是同一个决定。规则是数据（`config/tool_guard.json`），用户可编辑而不必读 Python。

**按能力匹配，而不是按类名**。规则同时匹配节点类名与它声明的 `capabilities`，能力由 `check_tool_call()` 自己从注册表取（调用方无需传参，也就不会忘记传）：

| 规则 | 命中 | 判定 |
| --- | --- | --- |
| `*requires_external_software*` | ORCA / VASP / GROMACS / LAMMPS / OpenMM / Psi4 / CP2K / Quantum ESPRESSO / Gaussian | `approval` |
| `*requires_network*` | PubChem / PDB / ChEMBL / Materials Project / ICSD / NIST / LLM 等 15 个 | `approval` |
| `*Submission*` / `*Export*` / `*Write*` | 覆盖既有交付物或写盘 | `approval` |
| `*` | 其余只读计算节点 | `allow` |

按能力而非类名的理由：类名会变（`Submission` 里并不含子串 `Submit`，凭直觉写的 `*Submit*` 匹配为空，是一条无人看守的死策略），而**「这个节点需要 shell 出外部程序」不会变**。新增节点自动继承判定，不需要改规则。规则若当前匹配不到任何节点，必须显式标 `forward_looking=True` 并有测试覆盖——「看着对但匹配为空」不是前瞻性策略。

策略文件路径锚定仓库根而非进程 CWD：桌面版从安装目录或快捷方式启动，CWD 相对路径会让用户写的规则被静默忽略、安全策略无声退回默认。

**为什么 `approval` 在这里不是弹窗**：Octop 是多用户服务，审批有第二个人；本项目是单用户桌面工作流，没有人可审批。伪造一个对话框比直接说不行更糟，因此 `approval` 表示「调用方必须显式批准」，Agent 节点把它作为明确拒绝上报。被拒节点**直接让任务失败**（`status: refused`）——记一条「denied」然后照常执行，比没有守卫更糟。

### 5.7 依赖方向

```
backend/ ─▶ foundation/ ai_runtime/ data_layer/ simulation_runtime/ ─▶ models/ simulations/ databases/
nodes/   ─▶ workflow_engine/（永不被 workflow_engine 反 import）
```

统一运行时层同样**只向下依赖**，可脱离引擎单独测试（见 `tests/test_v06.py`）。

## 6. 设计决策记录

| 决策 | 理由 |
| --- | --- |
| 节点间传对象而非文件路径 | 类型安全、可缓存、可单测；文件只在边界（IO 节点）出现 |
| 同步事件总线 | 科学工作流是 CPU 密集型，异步事件带来的复杂度大于收益 |
| 缓存默认关闭 | 可复现性是科学计算的第一需求 |
| 外部工具一律带回退 | 实验室机器上装不全 ORCA/GROMACS；平台必须永远能跑 |
| 参数用 `(value, label)` 元组 | 前端渲染中文下拉项，引擎拿到的是稳定的 value |
