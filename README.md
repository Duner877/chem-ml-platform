# Chem ML Platform v0.7.4

**节点化科学工作流平台** — ComfyUI 式的图形编排 × KNIME 式的数据处理 × LabVIEW 式的仪器抽象 × AI Scientist 式的自主推理。

> **v0.7.4（当前版本）**：这一版做的是「结构」和「入口」两件事。**节点库按设备分组（ComfyUI 模式）** —— 节点实现从 `nodes/` 迁到 `custom_nodes/`，按质谱、光谱、XPS、显微、衍射等设备类别分成 21 个自包含分组，每个分组一个目录；发现靠 `pkgutil.walk_packages` 递归遍历 + `@register_node` 装饰器自注册，导入即注册。以后加一个节点只要把文件放进对应目录，不用改注册表也不用改加载器。`nodes/` 保留成旧路径兼容门面，旧代码里的 `from nodes.instruments.ms import LCMSNode` 不用逐个手改 —— 而且两条路径指向的是**同一个模块对象**，源文件只执行一次（这条被回归测试锁住）。节点总数 **101 → 101**，分类 30 个不变，**零丢失零新增**。**软件更新入口** —— 界面顶栏常驻徽标，启动时后台问一次 GitHub 最新发布版，有新版才变色；点开是「检查 / 下载 / 启动安装」三步分开的更新面板，下载完校验 SHA-256 之后才交给安装程序，安装程序在应用退出后才运行，避免覆盖正在使用的可执行文件。版本比较走**数值**而不是字符串，`0.7.10` 比 `0.7.9` 新。检查失败（断网、404）会明说「检查失败」，不会谎报成「已是最新」。
>
> **v0.7.3**：这一版补了三块能直接用到真实任务上的能力。**API Key 有了图形入口** —— `ai_runtime/credentials.py` 存 9 家服务商的密钥，优先走系统密钥环，没有就退回 `config/credentials.json`；GUI 顶栏和左侧图标栏都是常驻入口，顶栏徽标在没配密钥时显示琥珀色。界面和接口只回掩码，不会把明文吐出来，另外提供了真实的连通性测试。**二维声学全波形反演（FWI）** —— `simulations/fwi.py` 配了梯度（`∂²u/∂t²` 形式）、频率递进、回溯线搜索和 held-out 监控，4 个新节点加上示例工作流 `09_seismic_fwi.json`，跑完能拿到赛题要的 `velocity_model.npy` / `wavelet.npy` / `run_summary.json`。**硬碳预脱溶剂的可视化计算化学模型** —— 取自 Nature Communications 15, 3497，4 个节点 3 条边连成证据链：尺寸筛分（4 Å 孔口）→ 静置老化 → 双 SEI 能量学 → 机制汇总与自洽检查，首效曲线锚在论文的 12 h / 90.14 % 和 10 天 / 99.09 % 两个实测点上。目前一共 101 个科学节点、30 个分类。

> **v0.7.1**：这一版是整改和工程补齐，五个词是可安装、可运行、可验证、可追溯、可维护，节点数量没刻意往上加。主要变更 —— **流式分块上传**（`storage/`，边收边校验，字节/超时/并发三重限额，`.part` 原子提交）、**本地 API 会话令牌与权限边界**（`backend/security.py`，只读 / 写入 / 执行 / 外部程序四类权限 + 审计日志 + CORS 白名单）、**Agent 真实执行状态机**（`agent_runtime/tasks.py`，Plan → 审批 → 执行 → 验证 → 完成，幂等指纹防重复提交，支持取消 / 拒绝 / 重试）、**节点能力标签与状态分级**（`capabilities` + implemented/executable/validated/experimental/unavailable，机器可读目录见 `docs/node-catalog.md`）、**受控外部程序执行服务**（`simulations/controlled.py`，固定可执行文件白名单 + 显式 argv + 独立工作目录 + 超时/并发限制，禁止任意 shell 字符串）、**LC-MS/MS 已知答案科学基准**（`scripts/benchmark_lcms.py`）、**依赖许可清单与 SBOM**、**扩展质量门禁**（`scripts/quality_gate.py`）。

**v0.7.0 Desktop Scientific AI OS**：在 v0.6.0 全部功能之上新增 —— 安全存储层（`storage/`）、统一错误模型（14 个错误码 + 密钥脱敏）、全运行溯源（`provenance.json`）、Agent 任务状态机、GPU/PyTorch 节点、三格式报告导出（DOCX / Markdown / HTML）、Electron 桌面外壳（`desktop/`）、安全文件上传 API、质量门禁。版本规划与审计文档见 `docs/V07_*.md`。

**v0.6.0 Scientific Foundation Model Edition**：统一科学基座模型运行时（`foundation/`，`embed / similarity / predict / describe / catalog` 五个稳定 API）、Cloud ⇄ Local AI 一键切换（`ai_runtime/`）、科学数据目录、仿真作业管理器、可运行 Agent + CLI、选项卡式工作台 Dock。

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React Flow](https://img.shields.io/badge/React%20Flow-12.x-ff4d8d.svg)](https://reactflow.dev/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![nodes](https://img.shields.io/badge/nodes-101-blueviolet.svg)](#节点目录)

---

## 目录

- [这是什么](#这是什么)
- [案例：铝晶胞弛豫与能带态密度](#案例铝晶胞弛豫与能带态密度)
- [快速开始](#快速开始)
- [架构](#架构)
- [节点目录](#节点目录)
- [Demo 工作流](#demo-工作流)
- [工作流 JSON 格式](#工作流-json-格式)
- [API](#api)
- [编写自定义节点](#编写自定义节点)
- [Docker 部署](#docker-部署)
- [开发与测试](#开发与测试)
- [深度文档](#深度文档)
- [路线图](#路线图)
- [许可证](#许可证)

---

## 这是什么

Chem ML Platform 把**科学研究**拆成可复用的节点，用有向无环图（DAG）串成完整工作流：

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ 质谱文件  │ → │ 峰提取    │ → │ 平滑      │ → │ 未知物鉴定 │ → │ 报告导出  │
│ .xy/.mzML│   │ PeakPick │   │ SavGol   │   │ 多证据融合 │   │ MD/HTML  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

**设计上比较在意的几点**

| 做法             | 说明                                                                                                                               |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **科学对象协议** | 节点之间传递的是 `Spectrum` / `Molecule` / `Material` / `Table` / `Image` / `Text` / `ScientificReport` 等强类型对象，而不是裸文件 |
| **确定性优先**   | 每个计算都有固定随机种子，同样的输入永远得到同样的输出                                                                             |
| **优雅降级**     | 外部工具（ORCA、GROMACS、PubChem、LLM API）不可用时自动回退到内置引擎，并在元数据中标注 `engine`                                   |
| **实现完整**     | 仓库中不含占位实现，每个文件都是可运行代码                                                                                         |

---

## 案例：铝晶胞弛豫与能带态密度

完整说明见 **[docs/cases/al-fcc/README.md](docs/cases/al-fcc/README.md)**。
工作流文件：[`workflows/11_solid_state_dft.json`](workflows/11_solid_state_dft.json)
— 14 个节点 / 17 条边，本机实跑 `completed` / 0 错误。

给一块铝，问三个问题：最舒服的晶格常数是多少（弛豫）、电子能怎么分布（能带）、
费米面附近有没有态（态密度，是金属还是绝缘体）。这个案例把三次计算串成一张图，
并且让后两次跑在**第一次弛豫出来的那个晶胞**上。

```
MaterialInputNode  铝(fcc) a=4.05Å
        │
        ▼
ABACUSNode cell_relax ──► a 4.050 → 3.987 Å（实验 4.05，误差 −1.6%）
        │ material（弛豫后的晶胞，不是原始的）
        ├─────────────┬─────────────┐
        ▼             ▼             ▼
   bands 节点      dos 节点      pdos 节点
   a=3.987Å       a=3.987Å      a=3.987Å
   gap 0.000eV    DOS(E_F)=      p 轨道主导
   E_F −6.851eV   0.2152 st/eV
        │             │             │
        ▼             ▼             ▼
    能带图.png     态密度.png    PDOS.png
```

能量、力、应力三条收敛曲线量纲不同且相差三到四个数量级，所以拆成三张图。

### 六张产物图（本机实跑产出）

| 产物图                                            | 关键结果                                                     |         |                   |
| ------------------------------------------------- | ------------------------------------------------------------ | ------- | ----------------- |
| ![能带](docs/cases/al-fcc/Al_能带图.png)          | 4 条带；`gap = 0.000 eV`，费米面处有带穿过 → 金属            |         |                   |
| ![态密度](docs/cases/al-fcc/Al_态密度_DOS.png)    | 费米面处态密度非零 → 金属                                    |         |                   |
| ![PDOS](docs/cases/al-fcc/Al_投影态密度_PDOS.png) | 费米面附近几乎全部来自 p 轨道，s 贡献极小 → 符合 3s²3p¹ 构型 |         |                   |
| ![能量](docs/cases/al-fcc/Al_弛豫能量收敛.png)    | 单调下降，第 2 步起平台                                      |         |                   |
| ![力](docs/cases/al-fcc/Al_弛豫力收敛.png)        | 残余力 F 降到 ~6×10⁻⁴ eV/Å                                  |         |                   |
| ![应力](docs/cases/al-fcc/Al_弛豫应力收敛.png)    | 残余应力降到 ~7×10⁻³ GPa                                    |         |                   |

只有 4 条带，是因为 Al 原胞 1 个原子 × 4 个轨道（1s + 3p），`d` 轨道数为 0。
这是模型本身的上限——要更多带得引入 d 轨道或者改用超胞。

### 这份结果该怎么看

站得住的部分：晶格常数误差 −1.6 %；带隙 0 与「金属性」判定完全正确；
六张图全部交付，弛豫后的晶格常数在三个下游节点间一致（容差 0.01 Å，有测试断言）。

有偏差的地方：内置 Al 参数的**能带色散方向目前是颠倒的**——
Γ 点最低带（−3.00 eV）高于 X 点最低带（−10.68 eV），物理上应当相反。
直接翻转符号会得到 −25 eV 的非物理结果，所以这是 onsite 能与 hopping 积分
需要**整体重新标定**，不是符号写反了。

另外，Al 的电声/强关联修正不在本模型内。**绝对数值请以 DFT 为准**。
这个案例想说明的是「全流程可跑通、产物完整、跨节点自洽可校验」，
拿它当可发表的电子结构结果还不行。

`ABACUSNode` 在未安装 ABACUS 的机器上会回退到内置引擎 `internal:tight-binding`，
同时照常生成 ABACUS 的 `INPUT` / `STRU` 输入卡；装了 ABACUS 则走 `external:abacus`
并真实读取 `BANDS_*.dat` / `OUT.ABACUS`。

---

## 快速开始

### 方式一：本地运行（推荐开发者）

```bash
# 1. 安装依赖
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ./node_sdk/python                    # 节点 SDK（写插件必需）

# 2. 启动后端（FastAPI，含 101 个科学节点）
uvicorn backend.app:app --reload --port 8000

# 3. 启动前端（React Flow 编辑器）
cd frontend && npm install && npm run dev
```

打开 <http://localhost:5173>，左侧拖节点 → 连线 → 点 **运行**。

### 方式二：Docker 一键部署

```bash
docker compose up --build
# 打开 http://localhost:8000
```

### 方式三：命令行跑 Demo

```bash
# 列出 / 运行全部 11 个官方 Demo 工作流
python scripts/run_demo_workflows.py --list
python scripts/run_demo_workflows.py

# 全节点冒烟测试（101 个节点逐一实例化并执行）
python scripts/smoke_nodes.py
```

---

## 架构

```
chem-ml-platform/
├── frontend/            React 18 + TypeScript + React Flow + Tailwind（三栏 ComfyUI 式编辑器 + 选项卡工作台）
├── backend/             FastAPI：REST + WebSocket，节点目录 / 工作流 CRUD / 执行 / 产物下载
│   └── routers/         nodes · workflows · runs · ws · ai · agent · data · simulations · foundation
├── workflow_engine/     核心引擎：ScientificNode 基类、节点注册表、DAG 执行、事件总线、缓存
│   └── parsers/         mzML · mzXML · MGF · MSP · JCAMP · XY · Bruker 谱图解析
├── foundation/          统一科学基座模型运行时（registry + embed/similarity/predict/describe/catalog）
│   ├── base.py          FoundationModel 基类 · FoundationRegistry · seed_vector · registry 单例
│   ├── molecular.py     ChemBERTa / GROVER / Graphormer / Uni-Mol / Morgan / Descriptor-Vector / Physchem
│   └── spectral.py      Spectrum-Bin / Spectrum-Summary 谱图编码器
├── ai_runtime/          AI Runtime + Cloud/Local 切换（config.py 持久化 config/ai.json）
├── database_runtime/    统一数据库检索运行时（Spectral / Chemical / Materials，离线回退本地库）
├── simulation_runtime/  统一仿真运行时（四段流水线）+ 作业管理器 jobs.py
├── data_layer/          统一科学数据层 + 可检索目录 catalog.py（带基座嵌入）
├── report_agent/        报告代理：Markdown / HTML / PDF 一键生成
├── node_registry/       节点注册中心服务，导出 registry.json 供前端 Node Marketplace
├── custom_nodes/        节点库（ComfyUI 模式）：21 个设备分组，101 个科学节点（见下方目录）
├── nodes/               旧路径兼容门面（与 custom_nodes 指向同一模块对象，勿直接新增实现）
├── models/              计算层：SMILES 解析、描述符、指纹、EHT 量子化学、分子动力学、谱学模拟
├── simulations/         Extended Hückel / 紧束缚 / Lennard-Jones MD / 外部程序封装
├── databases/           本地分子库（~400 化合物）与材料库（18 种材料）
├── datasets/            真实科研数据集（EI-MS 谱、分子库 CSV、电池候选 CSV、SEM 等）
├── workflows/           11 个官方 Demo 工作流 JSON
├── config/              运行时配置（ai.example.json 模板；ai.json 本地生成、不入库）
├── node_sdk/            Python SDK（chemml_sdk）+ Node.js SDK
├── tests/               pytest：引擎 / 节点 / 工作流 / API / 基座模型，967 项
├── scripts/             smoke_nodes.py · run_demo_workflows.py · run_agent.py · package.py
├── examples/plugins/    插件示例（可直接运行的自定义节点）
├── plugins/             第三方节点目录（CHEMML_PLUGINS 默认指向此处）
├── docs/                深度文档：架构 · 节点开发 · 工作流格式 · API · 部署 · 任务书
├── .github/workflows/   CI：pytest · 全节点冒烟 · Demo 工作流 · Node SDK · 前端构建 · Docker
├── Dockerfile · docker/ · requirements.txt
└── README.md · LICENSE · CONTRIBUTING.md · CHANGELOG.md
```

**数据流**

```
React Flow 画布 ──POST /api/workflows/run──▶ WorkflowEngine
                                              │
                    ┌─────────────────────────┼──────────────────────────┐
                    ▼                         ▼                          ▼
            topological_generations   ThreadPoolExecutor          EventBus
            按代执行（并行）            （同代节点并行）        → WebSocket 实时事件
                    │
                    ▼
             ScientificObject（Pydantic v2）
                    │
                    ▼
             产物写入 output/<run_id>/artifacts/
```

---

## 节点目录

**101 个科学节点，30 个分类。**（完整机器可读目录见 [`node_registry/registry.json`](node_registry/registry.json)）

### 代码位置：按设备分组（ComfyUI 模式）

v0.7.4 起，节点实现放在 `custom_nodes/` 下，**按设备类别一个目录一个分组**，跟 ComfyUI 的自定义节点习惯一样：

| 分组目录 | 覆盖设备 | 分组目录 | 覆盖设备 |
| --- | --- | --- | --- |
| `mass_spectrometry/` | 质谱（LC-MS · GC-MS · MALDI · ICP-MS） | `surface_characterization/` | 表面表征（XPS · XAS） |
| `spectroscopy/` | 光谱（NMR · IR · Raman · UV-Vis） | `microscopy/` | 显微（SEM · TEM · AFM · 映射成像） |
| `thermal_analysis/` | 热分析（DSC · TGA · DMA） | `diffraction/` | 衍射（XRD · 单晶精修） |
| `electrochemistry/` | 电化学（CV · EIS） | `battery_materials/` | 电池材料 |
| `seismic/` | 声学 / 地震（FWI 反演） | `quantum_chemistry/` | 量子化学（EHT） |
| `materials_simulation/` | 材料仿真（紧束缚 · LJ-MD） | `molecular_dynamics/` | 分子动力学 |
| `databases/` | 数据库检索（谱库 · 分子库 · 材料库） | `foundation_models/` | 统一基座模型 |
| `ai_ml/` | AI / 机器学习 | `data_io/` | 数据导入导出 |
| `analysis/` | 通用分析 | `reporting/` | 报告生成 |
| `agent/` | 可运行 Agent | `questions/` | 顶层问题（未知物鉴定 · 材料发现） |
| `gpu/` | GPU / PyTorch | `_shared/` | 共享层（不注册节点） |

**加一个节点只需要两步**：把实现文件放进对应分组目录，加 `@register_node` 装饰器 —— 发现靠 `pkgutil.walk_packages` 递归遍历，**导入即注册**，不用改注册表，也不用改加载器。分组导出列表由 `scripts/generate_custom_node_packages.py` 从源码 AST 生成，导出与实现永远一致。

`nodes/` 保留为**旧路径兼容门面**：旧代码里的 `from nodes.instruments.ms import LCMSNode` 不用逐个手改。两条路径指向的是**同一个模块对象**，源文件只执行一次（这条由 `tests/test_v07_4_legacy_facade.py` 锁住）。

下面按**功能分类**列出全部节点。

### 顶层问题 `Questions`

| 节点                                | 说明                                                                                                        |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **Unknown Compound Identification** | 未知物鉴定：融合 MS 分子离子/碎片 + NMR 化学位移 + IR/Raman 谱带 + UV-Vis，输出候选结构、置信度与中英文解释 |
| **Material Discovery**              | 材料发现：融合 XRD/SEM/XPS/DFT 证据，按目标性质（比容量、电压、带隙…）对候选组分排序                        |

### 虚拟仪器 `Instruments`（26 个）

| 分类              | 节点                                                              |
| ----------------- | ----------------------------------------------------------------- |
| Mass Spectrometry | LC-MS · GC-MS · MALDI · ICP-MS                                    |
| NMR               | ¹H/¹³C NMR（化学位移表 + J 耦合多重峰 → FID → FFT）               |
| Vibrational       | IR · Raman（官能团谱带库匹配）                                    |
| Electronic        | UV-Vis（Woodward-Fieser）· Fluorescence（镜像对称 + Stokes 位移） |
| Surface           | XPS · XAS                                                         |
| Diffraction       | XRD（粉末衍射 + 指标化）· Single Crystal XRD（晶胞精修）          |
| Microscopy        | SEM · TEM · AFM（Ra/Rq 粗糙度）                                   |
| Thermal           | DSC · TGA · DMA                                                   |
| Electrochemistry  | CV · EIS（Nyquist/Bode）                                          |
| Particle          | DLS（动态光散射）· BET                                            |
| Imaging           | Raman Mapping · FTIR Imaging · Hyperspectral                      |

### AI `AI`（9 个）

| 分类              | 节点                                                                                                                                                                                        |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LLM               | **LLM Reasoner**：OpenAI / Anthropic / Google / DeepSeek / Qwen / Ollama / 离线推理                                                                                                         |
| Foundation Models | **ChemBERTa**（子词哈希）· **GROVER**（MPNN）· **Graphormer**（度/最短路径结构编码）· **Uni-Mol**（距离矩阵注意力）——v0.6 起统一由 [`foundation/`](#统一科学基座模型-foundation) 注册表驱动 |
| Vision            | **Vision Model**：ViT / CLIP / SAM / DINO 四种后端                                                                                                                                          |
| ML                | Train Model（PyTorch MPNN / NumPy 岭回归）· Property Prediction · Similarity Search                                                                                                         |

### 数据库 `Databases`（14 个）

| 分类      | 节点                                        |
| --------- | ------------------------------------------- |
| Spectral  | MassBank · MoNA · GNPS · HMDB · BMRB · NIST |
| Chemical  | PubChem · ChEMBL · ZINC · PDB               |
| Materials | Materials Project · COD · ICSD · AFLOW      |

### 模拟 `Simulation`（7 个）

| 分类               | 节点                                                              |
| ------------------ | ----------------------------------------------------------------- |
| Quantum            | ORCA · Gaussian · Psi4 · CP2K（生成真实输入文件 + 内置 EHT 回退） |
| Molecular Dynamics | GROMACS · LAMMPS · OpenMM（内置 Lennard-Jones 引擎 + RDF）        |

### 数据处理 `Analysis` / `IO` / `Report`

| 分类     | 节点                                                                                                                                                                 |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Analysis | Baseline Correction · Smoothing · Peak Picking · Normalize · Resample · Spectrum Math · Molecular Descriptors · Similarity · Substructure Search · Functional Groups |
| IO       | Spectrum File（mzML/mzXML/MGF/MSP/JCAMP/XY/Bruker）· Table File（CSV/TSV）· Molecule Input · Material Input · Text Input · Export                                    |
| Report   | Report Builder · Summary Table · Report Export（MD/HTML/JSON）                                                                                                       |

---

## Demo 工作流

### 1. 未知化合物鉴定 `workflows/01_unknown_compound_identification.json`

读取咖啡因 EI-MS 谱 → 峰提取 → Savitzky-Golay 平滑 → 与 ¹H NMR、IR 一起送入鉴定节点 → 在分子库中排序 → 导出候选 CSV + HTML 报告。

```
ms_file → ms_peaks → ms_smooth ─┐
nmr ─────────────────────────────┼→ identify → candidates (CSV)
ir ──────────────────────────────┘            → report → report_md (HTML)
library ─────────────────────────┘
```

### 2. 电池材料发现 `workflows/02_battery_material_discovery.json`

候选材料库 + LiFePO₄ 晶胞 → XRD 粉末衍射 → 峰检索 → 材料发现节点按质量比容量排序 → 汇总表 → 决策报告 + 优化材料 JSON。

### 3. 催化剂设计 `workflows/03_catalyst_design.json`

乙酰氯 + 苯 → ORCA 单点能 → ChemBERTa 嵌入 → 结构相似性检索 → LLM 方案设计 → 催化剂候选导出 + HTML 报告。

### 4. 量子化学性质剖析 `workflows/04_quantum_chemistry_profiling.json`

咖啡因 → 量子化学（EHT 回退）→ 分子描述符 → AI 性质预测 → Report Agent 输出 HTML 报告。

### 5. 多尺度材料模拟 `workflows/05_multiscale_materials_simulation.json`

水分子 MD（Lennard-Jones 回退）+ LiFePO₄ 固体 DFT（紧束缚回退）→ Report Agent 输出 HTML 报告。

### 6. 统一科学基座模型 `workflows/06_scientific_foundation_models.json`

分子输入 → ChemBERTa 嵌入 → Uni-Mol 嵌入 → 分子描述符 → Report Agent 汇总，演示 `foundation/` 注册表驱动的多编码器流水线。

### 7. mzML 质谱分析 `workflows/07_mzml_mass_spec_analysis.json`

读 mzML（MALDI DHB 基质单次扫描）→ 峰检测 → AI 助手辅助谱图解析与未知物鉴定（候选库检索 + 多证据打分）→ 报告代理汇总成 HTML 鉴定报告。

### 8. 硬碳预脱溶剂 `workflows/08_hard_carbon_predesolvation.json`

复现 Nat. Commun. 15, 3497 (2024) 的尺寸筛分预脱溶剂机制：按溶剂化结构特征尺寸判定能否穿过 ~4 Å 墨水瓶孔 → 过孔能垒与孔内 Na–P 配位 → 静置老化动力学 → 双 SEI 活化能证据链 → 汇总节点检查三条支路是否自洽。首效曲线锚在论文两个实测点上。

### 9. 二维声学全波形反演 `workflows/09_seismic_fwi.json`

从一维深度趋势出发，用伴随梯度全波形反演恢复横向速度结构，并写出赛题要求的三个文件：`velocity_model.npy` / `wavelet.npy` / `run_summary.json`。评分为深度均值去除后的横向相关系数，起点模型该值恒为 0。

### 10. 公众号营销文写作 `workflows/10_wechat_marketing_copy.json`

输入产品卖点与目标人群 → 模型产出选题策划（标题备选、卖点排序、开头钩子）→ 据此撰写正文成稿 → 汇总为结构化稿件并导出 Markdown。

### 11. 铝原胞弛豫与能带态密度 `workflows/11_solid_state_dft.json`

铝 fcc 晶格常数弛豫 → 在**弛豫后的同一个晶胞**上算能带、总态密度、分轨道态密度 → 交付 6 张关键产物图并汇总成 HTML 报告。详见下面的[铝晶胞案例](#案例铝晶胞弛豫与能带态密度)。

```bash
python scripts/run_demo_workflows.py           # 依次运行全部 11 个 Demo
python scripts/run_agent.py "咖啡因的溶解度如何？"   # Agent 命令行
```

---

## 统一科学基座模型 `foundation/`

v0.6 做的事主要是把分散的编码器 / 预测器收拢到**一个注册表 + 五个稳定 API**，节点只是薄适配器。

```python
from foundation import catalog, embed, similarity, predict, describe

print(catalog())                                   # 列出全部基座模型及其维度 / 能力
vec = embed("molecule", "CCO", model="morgan")      # 分子指纹向量（2048 维）
print(similarity("CCO", "CCCO"))                    # 乙醇 vs 丙醇 → 0.953
print(similarity("CCO", "c1ccccc1"))                # 乙醇 vs 苯   → -0.32
print(predict("molecule", "CCO", properties=["logp", "esol"]))
print(describe("chemberta"))                        # 单个模型的元数据
```


| 家族 family | 模型                                      | 维度                  | 能力                                     |
| ----------- | ----------------------------------------- | --------------------- | ---------------------------------------- |
| molecular   | ChemBERTa · GROVER · Graphormer · Uni-Mol | 384 / 512 / 768 / 512 | `embed`                                  |
| molecular   | Morgan · Descriptor-Vector                | 2048 / 18             | `embed`                                  |
| property    | Physchem                                  | —                     | `predict`（logp / esol / heavy_atoms …） |
| spectral    | Spectrum-Bin · Spectrum-Summary           | 128 / 8               | `embed`                                  |

> 没有权重时，基座模型用**确定性种子向量**（`seed_vector`），保证同输入同输出；`requires_weights` 字段标明哪些模型在提供权重后可切换到真实推理。返回的不会是随机结果。

---

## Cloud / Local AI 切换 `ai_runtime/`

```bash
# 一键切换运行模式
python -c "from ai_runtime import set_mode; set_mode('local')"    # 或 export CHEMML_AI_MODE=local
```

| 模式          | 含义                                                      |
| ------------- | --------------------------------------------------------- |
| `auto`        | 有密钥走云端，否则依次回退                                |
| `cloud`       | 强制云端（OpenAI / Anthropic / Google / DeepSeek / Qwen） |
| `local`       | 强制本地（Ollama 等本地推理）                             |
| `open_source` | 强制开源权重                                              |
| `chemistry`   | 强制化学专用后端                                          |
| `offline`     | 强制内置离线推理器                                        |

配置持久化在 `config/ai.json`（模板见 [`config/ai.example.json`](config/ai.example.json)，实际文件不入库），`family_order()` 始终把 `offline` 追加在末位，所以**任何模式下功能都不中断**；REST 接口 `GET/PUT /api/ai/config` 中的密钥以 `***` 掩码返回，写回时忽略掩码与空值。

---

## Agent 可运行 `custom_nodes/agent/` + `scripts/run_agent.py`

```bash
python scripts/run_agent.py "未知峰 m/z 194 可能是什么？" --mode auto
python scripts/run_agent.py -q "设计一个电池材料筛选流程" --no-llm --json
```

Agent 由 `ScientificAgentNode` / `AgentPlanNode` 驱动；规划器 `plan(..., use_llm=True)` 优先调用 `ai_runtime.complete` 生成计划，**拒绝 offline 引擎的产物**并回退到规则配方（回退原因写进报告元数据 `status / duration_ms / errors / records`）。REST 侧对应 `/api/agent/ask`、`/api/agent/plan`、`/api/agent/history`。

---

## 工作流 JSON 格式

```json
{
  "name": "我的工作流",
  "description": "一句话说明",
  "nodes": [
    {
      "id": "ms_file",
      "type": "SpectrumFileNode",
      "label": "质谱文件",
      "position": { "x": 0, "y": 0 },
      "params": { "path": "datasets/demo/caffeine_ms.xy", "technique": "MS" }
    }
  ],
  "edges": [
    {
      "source": "ms_file", "source_port": "spectrum",
      "target": "ms_peaks", "target_port": "spectrum"
    }
  ]
}
```

`edges` 也支持简写 `["a", "b"]`（自动取源/目标的第一个端口）。引擎会校验：节点 ID 唯一、类型已注册、无环、端口存在且类型兼容、必填端口已连接。

---

## API

后端提供 REST + WebSocket，交互式文档在 <http://localhost:8000/api/docs>。

| 方法        | 路径                                                                               | 说明                                      |
| ----------- | ---------------------------------------------------------------------------------- | ----------------------------------------- |
| `GET`       | `/api/health`                                                                      | 存活探针与节点总数                        |
| `GET`       | `/api/meta`                                                                        | 前端启动载荷（分类 + 全部节点规格）       |
| `GET`       | `/api/nodes`                                                                       | 节点列表（`?category=` / `?query=` 过滤） |
| `GET`       | `/api/nodes/categories`                                                            | 按分类分组的节点目录                      |
| `GET`       | `/api/nodes/{type}`                                                                | 单个节点完整规格                          |
| `GET`       | `/api/workflows`                                                                   | 已存储工作流列表                          |
| `GET`       | `/api/workflows/{file}`                                                            | 加载工作流 JSON                           |
| `POST`      | `/api/workflows`                                                                   | 校验并保存工作流                          |
| `POST`      | `/api/workflows/validate`                                                          | 仅校验                                    |
| `POST`      | `/api/workflows/run`                                                               | 执行内联工作流                            |
| `POST`      | `/api/workflows/{file}/run`                                                        | 执行已存储工作流                          |
| `GET`       | `/api/workflows/runs/{id}/events`                                                  | 运行事件历史                              |
| `GET`       | `/api/runs`                                                                        | 运行历史与产物                            |
| `GET`       | `/api/runs/artifacts/{path}`                                                       | 下载产物文件                              |
| `GET`       | `/api/ai/modes` · `/api/ai/providers`                                              | AI 运行模式与供应商列表                   |
| `GET`·`PUT` | `/api/ai/config`                                                                   | 读取 / 更新 AI 配置（密钥掩码）           |
| `POST`      | `/api/ai/complete` · `/api/ai/test`                                                | 直接调用 LLM / 连通性自检                 |
| `POST`      | `/api/agent/ask`                                                                   | 提问式 Agent（返回答案 + 依据 + 章节）    |
| `POST`      | `/api/agent/plan`                                                                  | 仅生成计划                                |
| `GET`       | `/api/agent/history`                                                               | Agent 运行历史                            |
| `GET`       | `/api/data/catalog` · `/api/data/catalog/{id}` · `/api/data/stats`                 | 科学数据目录                              |
| `POST`      | `/api/data/ingest` · `GET /api/data/datasets`                                      | 录入对象 / 列出数据集                     |
| `GET`       | `/api/simulations/families` · `/api/simulations/backends`                          | 仿真族与后端                              |
| `POST`      | `/api/simulations/run`                                                             | 提交仿真作业                              |
| `GET`       | `/api/simulations/jobs` · `/api/simulations/jobs/{id}`                             | 作业列表 / 详情                           |
| `GET`       | `/api/foundation/models`                                                           | 基座模型目录                              |
| `POST`      | `/api/foundation/embed` · `/api/foundation/similarity` · `/api/foundation/predict` | 嵌入 / 相似度 / 预测                      |
| `GET`       | `/api/update/current`                                                              | 当前版本（不联网）                        |
| `GET`       | `/api/update/check`                                                                | 检查 GitHub 最新发布版                    |
| `POST`      | `/api/update/download`                                                             | 下载安装包到本地缓存并计算 SHA-256        |
| `WS`        | `/api/ws/run/{run_id}`                                                             | 实时事件流                                |

**Python SDK**

```python
from chemml_sdk import ChemMLClient

client = ChemMLClient("http://127.0.0.1:8000")
print(client.health())                                  # {'status': 'ok', 'nodes': 101, ...}
run = client.run_workflow("01_unknown_compound_identification.json")
print(client.summary(run))                              # "...: completed (10 nodes, 1020 ms, 0 failed)"
print(run["records"]["identify"]["logs"])               # 每个节点的真实日志

# 也可以在进程内执行，无需 HTTP 后端
result = client.run_local({"name": "inline", "nodes": [...], "edges": [...]})
```

**Node.js SDK**

```js
import { ChemMLClient } from "chemml-node-sdk";

const client = new ChemMLClient("http://127.0.0.1:8000");
const run = await client.runWorkflow("02_battery_material_discovery.json");
console.log(client.summary(run));

const socket = client.stream(run.run_id);
client.on("event", (event) => console.log(event.type, event.node_id ?? ""));
```

---

## 编写自定义节点

### 方式一：放进 `custom_nodes/` 的设备分组（推荐）

v0.7.4 起，节点实现按设备分组放在 `custom_nodes/<分组>/` 下。选一个设备目录，放进去、加装饰器，重启即自动注册：

```python
# custom_nodes/mass_spectrometry/my_node.py
from chemml_sdk import ScientificNode, Port, ParameterSpec, register_node
from workflow_engine.objects import Text

@register_node
class MyMSNode(ScientificNode):
    name = "My MS Node"
    category = "Mass Spectrometry"
    description = "我的质谱节点。"
    version = "1.0.0"
    tags = ["demo"]

    input_ports = [Port("text", "Text", optional=True, multi=True)]
    output_ports = [Port("text", "Text")]
    parameters = [ParameterSpec("who", "string", "world", "问候对象")]

    def execute(self, inputs, ctx=None):
        return {"text": Text(text=f"hello {self.get_param('who')}!")}
```

分组目录清单见[节点目录](#代码位置按设备分组comfyui-模式)。发现机制是 `pkgutil.walk_packages` 递归遍历 + `@register_node` 自注册，**不用改注册表，也不用改加载器**。

各分组的 `__init__.py` 导出列表由 `scripts/generate_custom_node_packages.py` 从源码 AST 生成，加了新节点后跑一次它就不会漏导出：

```bash
python scripts/generate_custom_node_packages.py
```

### 方式二：`plugins/` 第三方插件目录

把下面这个文件放进 `plugins/`（或设置 `CHEMML_PLUGINS` 指向任意目录，如 `examples/plugins`），重启即自动注册：

```python
# plugins/my_node.py
from chemml_sdk import ScientificNode, Port, ParameterSpec, register_node
from workflow_engine.objects import Text

@register_node
class HelloNode(ScientificNode):
    name = "Hello Science"
    category = "Custom"
    description = "向操作员问好。"
    version = "1.0.0"
    tags = ["demo"]

    input_ports = [Port("text", "Text", optional=True, multi=True)]
    output_ports = [Port("text", "Text")]
    parameters = [
        ParameterSpec("who", "string", "world", "问候对象"),
        ParameterSpec("times", "integer", 1, "重复次数", min=1, max=10),
    ]

    def execute(self, inputs, ctx=None):
        who = self.get_param("who")
        times = int(self.get_param("times") or 1)
        self.log(f"greeting {who} {times}x")
        return {"text": Text(text=f"hello {who}! " * times)}
```

节点契约：

- 继承 `ScientificNode`，实现 `execute(self, inputs, ctx=None) -> dict`
- `inputs` 的键是输入端口名，值是科学对象（或多个对象组成的列表）
- 返回 dict 的键必须对应声明的输出端口名
- 参数通过 `self.get_param(name)` 读取（已按 `ParameterSpec` 做强转）
- 异常会被引擎捕获并标记该节点失败，下游自动跳过

完整指南见 [docs/node-development.md](docs/node-development.md)，可直接运行的示例见 [examples/plugins/](examples/plugins/)。

---

## Docker 部署

```bash
# 构建并启动（API + 预构建前端，单容器）
docker compose up --build

# 带 PostgreSQL / Redis（为将来的持久化与缓存预留）
docker compose --profile db up --build
```

环境变量：

| 变量                                                                                                 | 说明                                      |
| ---------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `CHEMML_PLUGINS`                                                                                     | 第三方节点插件目录（默认 `/app/plugins`） |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` | 启用对应的在线 LLM 供应商                 |
| `MP_API_KEY`                                                                                         | 启用 Materials Project 在线检索           |

未提供密钥时，LLM 节点使用内置离线推理器，数据库节点回退到本地库——**功能不中断，只是数据来源不同**。

---

## 开发与测试

```bash
# Python 测试（967 项：引擎 / 节点 / 工作流 / REST API / 基座模型与运行时）
pytest

# 全节点冒烟测试（逐一实例化并执行 101 个节点）
python scripts/smoke_nodes.py
python scripts/smoke_nodes.py --json > smoke.json     # 机器可读报告

# 运行全部 Demo 工作流
python scripts/run_demo_workflows.py
python scripts/run_demo_workflows.py --events         # 打印节点事件

# 前端
cd frontend
npm run lint        # tsc --noEmit
npm run build       # 生产构建
npm run dev         # 开发服务器（/api 代理到 :8000）

# Node SDK 测试
cd node_sdk/nodejs && npm test
```

---

## 深度文档

| 文档                                                                                                              | 内容                                                                                              |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [docs/cases/al-fcc/README.md](docs/cases/al-fcc/README.md)                                                        | **晶胞案例**：铝 fcc 弛豫 + 能带 + 态密度，6 张实跑产物图，哪些数字站得住、哪些站不住逐条标了出来 |
| [docs/architecture.md](docs/architecture.md)                                                                      | 四层架构、引擎执行模型、事件总线与缓存、科学对象协议、设计决策记录                                |
| [docs/node-development.md](docs/node-development.md)                                                              | 从零编写科学节点：端口、参数、`execute()` 契约、调试、测试、自检清单                              |
| [docs/workflow-format.md](docs/workflow-format.md)                                                                | 工作流 JSON 完整规范：节点、边（含简写形式）、端口兼容、运行时输入注入                            |
| [docs/api-reference.md](docs/api-reference.md)                                                                    | REST 与 WebSocket 逐端点参考、请求/响应示例、错误码速查                                           |
| [docs/deployment.md](docs/deployment.md)                                                                          | 本地 / Docker / 嵌入部署、环境变量、插件目录、生产检查清单、故障排查                              |
| [docs/v0.6-task-spec.md](docs/v0.6-task-spec.md)                                                                  | v0.6 任务书：统一科学基座模型版的范围、五大优先级、模块清单与验收标准                             |
| [examples/plugins/](examples/plugins/)                                                                            | 可直接运行的自定义节点示例                                                                        |
| [node\_sdk/python/README.md](node_sdk/python/README.md) · [node\_sdk/nodejs/README.md](node_sdk/nodejs/README.md) | 双 SDK 使用手册                                                                                   |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md)                                                 | 贡献指南与变更记录                                                                                |

---

## 路线图

```
v0.7.4            节点库按设备分组（ComfyUI 模式）· 软件更新入口  ← 当前版本：101 节点 · 11 Demo · 统一基座模型 · Cloud/Local AI 切换 · 可运行 Agent · 工具守卫 · 工作台 Dock
v0.7.3            可视化计算化学 · 二维声学 FWI · API Key 管理
v0.7           AI Scientist Agent（自主提出假设 → 设计实验 → 分析结果）
v1.0           Scientific Intelligence Operating System
```

---

## 许可证

[Apache License 2.0](LICENSE)

### 第三方与上游引用

| 内容         | 说明                                                                                                                                                                                                                                    |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 随包依赖     | 12 个 Python + 153 个 npm 包，逐条列在 [NOTICE](NOTICE) 与 [docs/THIRD_PARTY_LICENSES.md](docs/THIRD_PARTY_LICENSES.md)，许可信息取自真实安装元数据；SBOM 见 [sbom.json](sbom.json)                                                     |
| 外部科研软件 | ABACUS / CP2K / GROMACS / LAMMPS / ORCA / PSI4 / Quantum ESPRESSO 等**不随包分发**，平台仅在用户已安装时调用，缺失时回退内置近似                                                                                                        |
| 上游项目引用 | `agent_runtime/tool_guard.py` 借鉴了 [TencentCloud/Octop](https://github.com/TencentCloud/Octop)（MIT）的工具守卫**思路**（单点收口、风险分级、规则外置），没有复制上游的源文件；具体「借了什么 / 没借什么」见 NOTICE 与许可清单第 8 节 |
| 样例数据     | `datasets/` 下的数据由本项目生成或以 CC0 提供，每个数据集在 `*.metadata.json` 中自带 `license` 与 `source` 字段                                                                                                                         |

许可清单由 `scripts/license_report.py` 从真实元数据生成，`--check` 模式可验证未漂移：

```bash
python scripts/license_report.py --check
```
