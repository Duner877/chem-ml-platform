# Chem ML Platform v0.7.4

**节点化科学工作流平台** — ComfyUI 式的图形编排 × KNIME 式的数据处理 × LabVIEW 式的仪器抽象 × AI Scientist 式的自主推理。

这一版做两件事：**节点库按设备重组**，以及**软件更新入口**。

---

## 节点库按设备分组（ComfyUI 模式）

节点实现从 `nodes/` 迁到 `custom_nodes/`，按质谱、光谱、XPS、显微、衍射等 **21 个设备类别**各立一个目录：

```
custom_nodes/
├── mass_spectrometry/        质谱    LC-MS · GC-MS · MALDI · ICP-MS
├── spectroscopy/             光谱    NMR · IR · Raman · UV-Vis
├── surface_characterization/  表征    XPS · XAS · BET · DLS
├── thermal_analysis/          热分析  DSC · TGA · DMA
├── microscopy/                显微    SEM · TEM · AFM · 映射成像
├── diffraction/               衍射    XRD · 单晶精修
├── electrochemistry/          电化学  CV · EIS
├── battery_materials/         电池材料
├── seismic/                   声学 / 地震  FWI 反演
├── quantum_chemistry/         量子化学  EHT
├── materials_simulation/      材料仿真  紧束缚 · LJ-MD
├── molecular_dynamics/        分子动力学
├── databases/                 数据库检索
├── foundation_models/          统一基座模型
├── ai_ml/                     AI / 机器学习
├── data_io/                   数据导入导出
├── analysis/                  通用分析
├── reporting/                 报告生成
├── agent/                     可运行 Agent
├── questions/                 顶层问题（未知物鉴定 · 材料发现）
├── gpu/                       GPU / PyTorch
└── _shared/                   共享层
```

**加一个节点只需要两步**：把实现文件放进对应分组目录，加 `@register_node` 装饰器。发现靠 `pkgutil.walk_packages` 递归遍历，**导入即注册** —— 不用改注册表，也不用改加载器。

`nodes/` 保留为**旧路径兼容门面**：旧代码里的 `from nodes.instruments.ms import LCMSNode` 不用逐个手改，而且两条路径指向的是**同一个模块对象**，源文件只执行一次。

节点总数 **101 → 101**，分类 30 个不变 —— **零丢失、零新增**。

## 软件更新入口

- 界面顶栏常驻徽标，启动时后台问一次 GitHub 最新发布版，**只有真**有新版时才变色；
- 点开是「检查 / 下载 / 启动安装」三步分开的更新面板；
- 下载完成并校验 SHA-256 之后才交给安装程序；安装程序在应用**退出后**才运行，避免覆盖正在使用的可执行文件；
- 版本比较走**数值**而不是字符串 —— `0.7.10` 比 `0.7.9` 新；
- 断网或 404 会明说「**检查失败**」，不会谎报成「已是最新」。

---

## 迁移过程中修掉的十类缺陷

节点搬家不是挪文件而已 —— 过程中暴露了十类实质缺陷，其中三类是典型的「静默失效」：功能看起来在跑，实际走的却不是你以为的那条路径。

| # | 缺陷 | 症状 |
| --- | --- | --- |
| 1 | 兼容层让每个节点模块被执行了两次 | 同一文件两个模块对象，agent 状态机报出「本该 `WAITING_FOR_APPROVAL` 却直接 `RUNNING`」这种完全指错方向的问题 |
| 2 | 运行时产物落到了 `custom_nodes/output/` | 仓库根推导多了一层，**静默**变了；打包器拒绝出包 |
| 3 | 打包器只排除顶层的 `output/` | 产物目录不在顶层时规则看不见它 |
| 4 | 桌面打包缺少 `custom_nodes/` | 打包产物里 `cannot import name 'plan_question'`，源码树却正常 |
| 5 | 代码生成器会覆盖手写导出 | 规划器函数、工具注册表、`__version__` 一次重新生成后全部消失 |
| 6 | 旧包的一级导出静默丢失 | `from nodes.agent import __version__` 取不到；门面的两条入口给出**不同答案** |
| 7 | 版本号断言写死字面量 | 每发一次版都要改测试，忘了改就不再是断言 |
| 8 | `ExportNode` 导出 Markdown 必然崩溃 | —— |
| 9 | **`python -m nodes.loader` 命令崩了** | `runpy` 向 loader 取源码而非取已导入模块；兼容层缺 `get_code`。而这条命令自 0.7.3 起就写在文档、`CONTRIBUTING.md` 和排障表里，是用户发现「节点没出现」时第一个要跑的东西 |
| 10 | **`--plugins` 选项触发 TypeError** | `custom_nodes/loader.py` 里的 `load_nodes` 遮蔽了 `nodes` 包中同名的函数却不保留它的签名 |

第 9、10 项均为**导入路径正常、命令行崩溃** —— 只有开子进程跑 CLI 才能抓住，所以补的回归测试也必须开子进程。

---

## 实测数字

| 项目 | 结果 |
| --- | --- |
| 测试 | **967 项零失败**（unit / integration / security / benchmark / desktop） |
| 质量门禁 | **26 PASS / 0 FAIL / 1 SKIP**（唯一 SKIP 为无 CUDA） |
| 节点 | 101 个 · 30 个分类 · 21 个设备分组 |
| 工作流 | 无 torch 宿主机下 11 个 Demo 全部 `completed` / `failed: 0` |
| 桌面载荷 | 2/2 AGREES |

**未执行项（不计入 PASS）**：干净虚拟机安装验证、安装包代码签名、Linux/macOS 实机验证、**更新功能的真实端到端演练**（需先在 GitHub 上发布一个更高版本作为更新目标）、真实数据集的科研验证。

因此 v0.7.4 的定位是 **Alpha / Research Preview**。

---

## 资产

| 文件 | 说明 |
| --- | --- |
| `Chem-ML-Platform-v0.7.4.zip` | 完整源码归档 |
| `Chem ML Platform Setup 0.7.4.exe` | Windows 安装包（NSIS） |

哈希见仓库根目录的 `SHA256SUMS`，完整清单见 `docs/RELEASE_MANIFEST.json`，发布报告见 `docs/V07_4_RELEASE_REPORT.md`。

---

## 许可证

[Apache License 2.0](LICENSE)

第三方与上游引用见 `NOTICE` 与 `docs/THIRD_PARTY_LICENSES.md`，依赖清单见 `sbom.json`。
