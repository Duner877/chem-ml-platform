# Chem ML Platform v0.7.4 — 发布报告（V07_4_RELEASE_REPORT）

- **版本**：`0.7.4`
- **发布提交**：本报告**不写死提交哈希**——它无法记录包含自身的那个提交。请以
  `git describe --tags` 与 `docs/RELEASE_MANIFEST.json` 的 `commit` 字段为准。
- **执行环境**：Windows 11（win32 · AMD64）· Python 3.13.12（隔离 venv `chemml`）·
  Node.js 22.12.0 · 宿主机 Python 3.13.6（**无 torch**，桌面版实际使用）
- **配套材料**：`CHANGELOG.md`、`docs/PROVENANCE.md`、
  `docs/RELEASE_MANIFEST.json`、`SHA256SUMS`、`sbom.json`、`docs/THIRD_PARTY_LICENSES.md`

> ## 诚实性声明（本报告的第一原则）
>
> 本报告只记录**实际运行过**的命令与**真实回显**的数字。
>
> - 未执行的检查一律标注 **未执行 / NOT_PERFORMED / SKIP**，**绝不计入 PASS**；
> - **超时不是 FAIL，也不是 PASS**——状态是 NOT VERIFIED；
> - 内部近似算法**不宣称**为第三方科研软件的真实计算；
> - 合成基准成绩**不等同**于真实科研数据验证结论（二者分开表述）。

---

## 0. 一句话结论

v0.7.4 把节点库**按设备重组**，并新增**软件更新入口**。节点实现从 `nodes/` 迁到
`custom_nodes/`，按质谱、光谱、XPS、显微、衍射等 21 个设备类别各立一个目录，与
ComfyUI 的自定义节点习惯一致——新增一个节点只需要把文件放进对应目录，不需要改注册表
或加载器。节点总数 **101 → 101**，分类数 30 不变——**零丢失、零新增**。
（基线取 0.7.3 发布提交 `b7c0580` 的 AST 扫描实测值，不是 0.7.3 报告里那句
`99 nodes`：那是 10-17 的旧测量，0.7.3 发布前已修正为 101。）

同时新增软件更新入口：界面可自动检测是否有新版本、下载安装包并启动更新。

但本版更值得记录的不是这两项新功能，而是**节点迁移过程中暴露的八类实质缺陷**。
其中三类是典型的「静默失效」——功能看起来在跑，实际走的却不是你以为的那条路径：

1. **兼容层让每个节点模块被执行了两次。** 同一个文件在 `sys.modules` 里有两个不同的
   模块对象，源码与测试拿到不同副本。症状是 agent 状态机测试报出「本该
   `WAITING_FOR_APPROVAL` 却直接 `RUNNING`」——一个完全指错方向的现象。
2. **运行时产物落到了 `custom_nodes/output/`。** 仓库根的推导方式在迁移后多了一层，
   表达式**静默地**从仓库根变成了 `custom_nodes/`。写文件依然成功、产物依然生成，
   唯一的症状是发布打包器的泄漏扫描拒绝出包——三个文件卡住了每一次发布。
3. **代码生成器会覆盖手写导出。** 它靠 AST 找带装饰器的类，看不到规划器函数、工具
   注册表与 `__version__` 声明，于是一次重新生成就把它们全删了。
4. **旧包的一级导出静默丢失。** 兼容门面的伞包只从子模块收集导出名，而
   `INTENT_KEYWORDS`、`__version__` 定义在现代包**自己**身上——`nodes.agent` 一度
   只剩 8 个名字（0.7.3 有 23 个）。更糟的是门面的两条入口给出不同答案：实际生效的
   是导入时的预建那份，它恰好不认识现代包自身的 `__all__`。

**仍未完成**：干净虚拟机安装验证、安装包代码签名、Linux/macOS 实机验证、更新功能的
真实端到端演练（需先在 GitHub 上发布一个更高版本）、真实数据集的科研验证。因此
v0.7.4 的定位是 **Alpha / Research Preview**。

---

## 1. 本版改动

### 1.1 节点库按设备分组（ComfyUI 模式）

`custom_nodes/` 下 21 个设备分组 + `_shared` 共享层：

| 分组 | 设备类别 | 分组 | 设备类别 |
| --- | --- | --- | --- |
| `mass_spectrometry` | 质谱（LC/GC/ICP/MALDI、碎片化） | `materials_simulation` | 材料计算（ABACUS/VASP/QE） |
| `spectroscopy` | 光谱（UV-Vis/荧光/IR/Raman/NMR/成像） | `molecular_dynamics` | 分子动力学（GROMACS/LAMMPS/OpenMM） |
| `surface_characterization` | 表面与物性（XPS/XAS/BET/DLS） | `databases` | 数据库（谱库/化学/材料） |
| `thermal_analysis` | 热分析（TGA/DSC/DMA） | `foundation_models` | 基座模型（ChemBERTa/GROVER/Graphormer/UniMol） |
| `microscopy` | 显微（SEM/TEM/AFM） | `ai_ml` | AI / ML（LLM/视觉/预测/训练） |
| `diffraction` | 衍射（XRD/单晶） | `data_io` | 数据输入输出 |
| `electrochemistry` | 电化学（CV/EIS） | `analysis` | 通用分析 |
| `seismic` | 地震（采集/正演/FWI） | `reporting` | 报告与出图 |
| `battery_materials` | 电池材料（脱溶剂/双SEI/老化） | `agent` | 科学智能体 |
| `quantum_chemistry` | 量子化学（ORCA/Gaussian/Psi4/CP2K） | `questions` | 科学问题 |
| | | `gpu` | GPU 计算 |

- **发现机制**：`pkgutil.walk_packages` 递归遍历 + `@register_node` 装饰器自注册。
  导入即注册，无需登记。`custom_nodes/__init__.py` 提供 `discover()` / `device_groups()` /
  `node_specs()` / `node_categories()`。
- **旧路径继续可用**：`nodes/` 保留为兼容门面。源码内实测 **431 处** `from nodes.* import`
  仍然有效，其中指向节点实现的 **81 处**（`nodes.ai.*` 60、`nodes.instruments.*` 20、
  `nodes.question.*` 1）不必逐个手改——手改正是最容易「编译通过、运行时才炸」的
  一类批量编辑。门面的实现方式是 `meta_path` 别名转发，不是把类复制一份。
- **迁移可追溯**：`scripts/migrate_to_custom_nodes.py`（迁移脚本）与
  `scripts/generate_custom_node_packages.py`（从源码 AST 读出带 `@register_node` 的类，
  生成各分组 `__init__.py`，导出列表与实现永远一致）。

### 1.2 软件更新入口

- **后端** `backend/routers/update.py`：`GET /api/update/current`（不联网）、
  `GET /api/update/check`（问 GitHub 最新发布版）、`POST /api/update/download`
  （下载安装包到本地缓存并计算 SHA-256）。
- **版本比较是数值而非字典序**：`0.7.10` 比 `0.7.9` 新，字符串比较会反过来。
  字典序比较的版本检查比没有检查更糟——用户会据此跳过修复了数据缺陷的版本。
- **网络失败不是错误**：返回 `{"update_available": false, "check_failed": true}`。
  离线被说成「已是最新」是一种谎报，界面据此说「检查失败」。
- **界面**：右侧工作台新增「更新」标签页（`UpdatePanel.tsx`：检查 / 下载 / 启动安装
  三步分开，下载完成并校验后才交给安装程序）；顶栏新增徽标（`UpdateBadge.tsx`：
  启动时后台检查一次，**只有真的有新版时才变色**，点开进入更新面板）。
- **桌面端**：`desktop/src/main.js` 新增 `install-update` IPC。安装包必须**在应用退出后**
  运行，否则会撞上「正在使用的可执行文件无法覆盖」；因此先以 detached 方式启动安装
  程序，再退出本进程。`desktop/src/preload.js` 暴露 `installUpdate`。
- **回归测试** `tests/test_v07_4_update.py`（27 项）：数值版本比较（含 `0.7.10 > 0.7.9`
  这一对字符串比较必错的例子）、离线不等于最新、404 表示「尚未发布」而非故障、blockmap
  不得当作安装包、**界面入口的静态断言**（后端存在但用户找不到，等于没有）。
- **回归测试** `tests/test_v07_4_legacy_facade.py`（27 项）：旧导入路径的兼容保证
  （见 §1.3 第 7 项）。

### 1.3 修复的八类缺陷

| # | 缺陷 | 症状 | 根因 |
| --- | --- | --- | --- |
| 1 | 兼容层让模块被执行两次 | agent 状态机报「该等审批却直接运行」 | finder 交出 modern 模块的 `__spec__`，其 `name` 是新路径，import 机制据此重跑源文件 |
| 2 | 运行时产物落到 `custom_nodes/output/` | 打包器拒绝出包（3 个文件卡住每次发布） | `parents[1]` 在迁移后多了一层，静默地从仓库根变成 `custom_nodes/` |
| 3 | 打包器只排除顶层 `output/` | 文件进归档，直到打包后扫描才发现 | 规则写成 `startswith("output/")` |
| 4 | 桌面打包缺 `custom_nodes/` | 打包产物里 `ImportError`，源码树正常 | `extraResources` 只列了 `../nodes` |
| 5 | 生成器覆盖手写导出 | `plan_question` 等在打包产物里导入失败 | 生成器靠 AST 找带装饰器的类，看不到无装饰器的导出 |
| 6 | 版本断言写死字面量 | 每次发版都要改测试，忘改就不再是断言 | 断言写成 `"0.7.3"` 而非引用单一真相源 |
| 7 | **旧包的一级导出静默丢失** | `from nodes.agent import __version__` 等 16 个名字取不到 | 伞包只聚合子模块的 `__all__`，漏掉定义在**现代包自身**上的名字 |
| 8 | 仓库内的临时目录未列入 `.gitignore` | 扫描器把测试夹具当成泄漏的密钥，全量测试 4 项失败 | 扫描器按 `.gitignore` 判断豁免，`.tmp/` 不在其中 |

第 7 项是本版最隐蔽的一类：迁移把 `nodes/agent/` 里的实现挪走后，兼容门面的
伞包（`nodes.agent`、`nodes.instruments` 等 7 个）只从**子模块**收集导出名，
而 `INTENT_KEYWORDS`、`__version__` 这类名字定义在现代包 `custom_nodes.agent`
**自己**身上——于是它们不在任何子模块的 `__all__` 里，也就没人转发它们。

实测对照 0.7.3 发布提交（`b7c0580`）的 `__all__`：

| 旧包 | 0.7.3 导出数 | 修复前可访问 | 修复后 |
| --- | --- | --- | --- |
| `nodes.agent` | 23 | **8** | 23 |
| `nodes.instruments` | 36 | **35**（缺 `InstrumentNode`） | 51 |
| `nodes.ai` | 12 | 15 | 15 |
| `nodes.simulation` / `nodes.databases` / `nodes.question` / `nodes.gpu` | 13 / 17 / 5 / 5 | 一致 | 一致 |

修法不是「再补几个名字」，而是把两条入口（meta-path finder 与导入时的预建）
**合并到同一个聚合函数** `_build_umbrella`。此前它们是同一段逻辑的两份拷贝，
已经漂移过一次：预建那条路径不认识现代包自身的 `__all__`，而实际生效的恰恰
是预建的那一份——**门面按「怎么走到它」给出不同答案**，这种失败是间歇性的，
比一直答错更糟。

第 8 项与前七项无关，是本轮复核时撞上的：全量测试跑出 4 项失败，全部指向
「扫描器报出 9 个泄漏的凭据文件」。查下去那些文件是**测试自己造的夹具**——
`--basetemp` 指在了仓库内的 `.tmp/`，而扫描器按 `.gitignore` 判断哪些路径算
豁免，`.tmp/` 不在其中，于是夹具里的 `credentials.json` 被当成了真实的密钥泄漏。
修法是补一条 `.gitignore`（`.tmp/`），而不是放宽扫描器：**放宽扫描器会让真正的
泄漏一起通过**，那才是危险的修法。

新增回归测试 `tests/test_v07_4_legacy_facade.py`（27 项）：基线**从 git 读出**
0.7.3 的实际 `__all__`（不是抄进测试文件——抄进去的那份会在生产代码改坏后
继续通过，与回归测试的职责相反），并断言两条入口给出相同的导出集合。
反向验证：退回「现代包自身不参与聚合」后 2 项失败。

另修复**构建戳的 `dirty` 判据**：它原本用 `git status --porcelain` 全量判断，而发布
流程恰恰要求清单与校验和清单**保持未提交**（记录了自身提交的清单无法存在于那个提交
里），于是每次打包都写 `dirty: true`——这句话的含义是「你运行的代码可能不是这个提交
里的代码」，在这里是假的。判据改为只统计源码改动。

修这个判据时又暴露了它自己的 bug：解析用的是 `line.strip()[3:]`，把行首的状态列也
去掉了，于是 `" M SHA256SUMS"` 被读成 `"HA256SUMS"`——排除**静默失效**，而且失效得
最彻底的就是它本该排除的那几个文件。解析逻辑抽成可测函数，测试直接调用生产代码；
反向验证确认退回旧写法后 3 项判据测试失败。

### 1.4 其他变更

- `scripts/version.py` 的版本扫描目标 `nodes/agent/__init__.py` →
  `custom_nodes/agent/__init__.py`。
- `tests/test_v07_3_unbound_names.py` 的扫描目录跟随迁移（否则它会只扫一个门面文件
  然后永远通过——那正是守卫最不该有的失败模式）。
- `nodes/__init__.py` 的两条入口合并为共享的 `_build_umbrella`（见 §1.3 第 7 项）。
- 界面「关于」对话框中的版本描述更新为 0.7.4。
- `CHANGELOG.md` 新增 `[0.7.4]` 条目。

---

## 2. 实测结果

下表**只记录实际运行的命令**。

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `python -m pytest tests/ -q` | **962 项执行，零失败零错误**，见 §2.1 | 全量套件 |
| `python scripts/quality_gate.py` | **PASSED**（26 PASS / 0 FAIL / 1 SKIP），见 §2.2 | 质量门禁 27 阶段 |
| `python scripts/version.py --check` | `OK: every artefact agrees on 0.7.4` | 版本一致性 |
| `python scripts/license_report.py --check` | `[PASS]`，见 §2.3 | 第三方许可证 |
| `python scripts/dataset_governance.py --check` | `OK: 10 dataset metadata records are consistent` | 数据集治理 |
| `python scripts/release_manifest.py` | 清单已生成，见 §2.4 | 发布清单 |
| `python scripts/package.py` | `460 files · scan : clean`，见 §2.5 | 源码归档 |
| 前端 `npm run build`（tsc + vite） | `tsc clean` · 3 files | 生产构建 |
| `desktop` 构建（NSIS） | `Setup 0.7.4.exe`（约 75.6 MiB），见 §2.6 | 安装包 |
| 打包载荷后端导入（`D:/python 3.13.6`，**无 torch**） | `66 routes` · 3 个 update 端点 · `plan_question` 可导入 | 见 §2.7 |
| 打包载荷工作流实跑（无 torch 宿主机） | `status: completed` · `failed: 0` · 101 节点 | 见 §2.7 |
| `node_registry` 校验 | `101 node types, schemas valid` · 30 分类 | 注册表 |
| 演示工作流 dry-run | `11/11 workflows executed successfully` | 门禁阶段 |
| 更新功能的**真实端到端演练** | **未执行 / NOT_PERFORMED** | 见 §2.8 |

### 2.1 全量测试

`python -m pytest tests/ -q` → **962 项执行，全部通过，零失败零错误**。分类普查
（call phase）：

| 分类 | 通过 |
| --- | --- |
| unit | 468 |
| integration | 296 |
| security | 135 |
| benchmark | 18 |
| desktop | 45 |
| **合计** | **962** |

新增 `tests/test_v07_4_update.py`（27 项）：12 项覆盖版本号解析与数值比较
（含 `0.7.10 > 0.7.9` 与 `v0.7.4` 前缀），10 项覆盖更新端点与界面入口
（注册、离线、404、无新版、blockmap 排除、HTTPS 校验、GUI 入口），
5 项覆盖构建戳的 `dirty` 判据。

新增 `tests/test_v07_4_legacy_facade.py`（27 项）：以 **git 中 0.7.3 的实际 `__all__`**
为基线，逐个旧包断言导出名一个不少（7 个伞包 × 参数化 + 基线非空守卫），
断言两条入口给出相同集合、facade 走的是共享聚合函数、别名模块是同一对象、
`isinstance` 跨路径成立。

### 2.2 质量门禁

`python scripts/quality_gate.py` → **PASSED**，27 个阶段中 **26 PASS / 0 FAIL / 1 SKIP**。

SKIP 的那一项是 `host_gpu_status`：本机为 `torch 2.14.1+cpu`，**无 CUDA**。
这是主机能力缺失，不是产品缺陷，也不计入 PASS。

### 2.3 第三方许可证

`python scripts/license_report.py --check` → `[PASS] licence/SBOM report (12 py / 153 npm / 10 external)`。
备注：`faiss-cpu` 为可选组件、本机未安装——这是能力降级，不是失败。

### 2.4 发布清单

`python scripts/release_manifest.py` → `wrote docs/RELEASE_MANIFEST.md,
docs/RELEASE_MANIFEST.json, SHA256SUMS (20/21 built)`。

清单摘要：`{"declared": 21, "built": 20, "tested": 19, "published": 0, "not_built": 1}`。
未构建的那 1 项是 `ci-pipeline-json`——它由 CI 运行产生，本机没有 CI。

按流程约定，清单**不随源码提交**——记录了自身提交的清单无法存在于那个提交里。

### 2.5 源码归档

`python scripts/package.py --name Chem-ML-Platform-v0.7.4` →

```
files   : 460
payload : 约 5.4 MiB
size    : 约 1.9 MiB (compressed)
scan    : clean (no secret patterns, no forbidden paths)
```

> `files` 与 `scan` 是确定性的；两个字节数只给量级，因为归档**包含本报告**——
> 报告一改，归档的字节数就跟着变，写死精确值等于给下一轮埋一个必错的数字。
> 精确字节数与哈希以 `SHA256SUMS` 为准。

归档内容实测：`custom_nodes/` 25 个包的 `__init__.py` 齐备；`nodes/__init__.py`
兼容门面在列；**无** `output/`、`__pycache__`、`node_modules` 条目；`BUILD_INFO.json`
在列而 `RELEASE_MANIFEST` 不在列（按设计随包发布的是清单的旁置副本）。

### 2.6 安装包

`desktop` 的 NSIS 构建 → `Chem ML Platform Setup 0.7.4.exe`，**约 75.6 MiB**。

> 关于为什么不写精确字节数：NSIS 会把构建时间戳嵌进安装包，因此同一份源码
> 每次打包的字节数会差几十个字节（本轮实测在 79,228,068 与 79,228,091 之间
> 跳动）。报告里写死一个数，下一次构建它就是错的。**精确字节数与哈希以
> `SHA256SUMS` 为准**——那才是可校验的那一份。

构建戳记录 `dirty: false`，其 `commit` 字段与 `docs/RELEASE_MANIFEST.json` 的
`commit` 一致——即安装包与源码提交一致。这一点在本版之前是做不到的（见 §1.3 关于
`dirty` 判据的说明）。

桌面载荷一致性：`scripts/refresh_desktop_payload.py --verify --all-installed` →
**2/2 `AGREES`**（仓库内的 `win-unpacked` 与用户实际安装的那份）。

### 2.7 打包载荷在**无 torch** 宿主机上的验证

桌面版实际使用 `D:/python 3.13.6`（**无 torch**），因此验证必须在这个解释器上做。

- 后端导入：`66 routes`，三个 update 端点（`/api/update/check`、`/api/update/current`、
  `/api/update/download`）均在 OpenAPI 文档中；`from nodes.agent import plan_question`
  成功（这正是 §1.3 第 4 项缺陷曾导致打包产物报错的地方）。
- 节点注册：`71 modules / 101 nodes / 30 categories`。
- 工作流实跑（`workflows/11_solid_state_dft.json`）：`validate errors: []`、
  `status: completed`、`failed: 0`。

### 2.8 更新功能的真实端到端演练：未执行

**NOT_PERFORMED。** 完整的「检测 → 下载 → 启动安装」链路需要 GitHub 上存在一个
**比 0.7.4 更新**的发布版；本仓库当前唯一的发布版是 0.7.3，因此检查会正确地回答
「当前已是最新」，下载与安装两步没有可用的目标。

已验证的部分：三个端点已挂载并返回预期结构；版本比较的数值语义有 12 项测试覆盖；
界面入口存在且可点；`install-update` IPC 在主进程已注册。**未验证**的部分：真实网络
下载、真实安装包启动、应用退出后的替换流程。这一项**不计入 PASS**，需在发布 0.7.5
之后补做。

### 2.9 未执行的检查

| 项目 | 原因 |
| --- | --- |
| 干净虚拟机安装验证 | 无目标虚拟机 |
| 安装包代码签名 | 无证书 |
| Linux / macOS 实机验证 | 本机为 Windows |
| 更新功能的真实端到端演练 | 见 §2.8 |
| CUDA 相关能力 | 本机无 CUDA（门禁阶段 SKIP） |
