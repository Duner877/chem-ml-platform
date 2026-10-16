# Changelog

本文件记录 Chem ML Platform 的显著变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.7.3] — 2026-10

**三项赛题对齐版本。** 硬碳预脱溶剂机理可视化、二维声学全波形反演、以及配套的 Agent 与 API Key 入口改造。节点总数 94 → **99**。发布前对 0.7.3 新增代码做了两轮独立审查，本轮修复的缺陷列在末尾「修复 Fixed」中。

### 新增 Added

**二维声学全波形反演（赛题：Recover the subsurface structure from a seismic line, starting from a one-dimensional trend）**
- `simulations/fwi.py`（新增）：二维常密度声学有限差分求解器。正演为二阶时间 / **二阶空间**中心差分——四阶空间格式用镜像闭包处理地表时破坏算子对称性，产生本征模态不稳定，实测在几百步内发散到 1e+20，且阻尼越强越糟；改二阶后在三档阻尼下输出均约 1.7e-07。吸收层只作用于深部与两侧，地表行保留（该采集全部炮点/检波点都在 row 0，浅层阻尼等于把波场乘 0），地表用**对称 Neumann 闭包**。
- **源子波由最小二乘反演，不做假设**：以 `S = argmin Σ‖d − s*g‖²` 形式在**短滤波器**（L = nt/8 样本）上求解，正规方程由互谱 `Σ|G|²` 与 `Σ conj(G)D` 反变换得到的 Toeplitz 矩阵构成。两种被否掉的写法连同原因记录在 `estimate_wavelet` 的文档字符串里：单道滞后窗反卷积因单道格林函数存在深零点，相关系数只有 0.26；全长分频域相除则因 `R(f)/max(R)` 只在 2049 个频点中的 291 个高于 1e-3，60 Hz 以上格林函数能量不足峰值 1e-4。现版本起点模型下与注入子波相关 **0.873**，模型正确时为 **1.000**。
- **伴随梯度**取 `+(2/v)·∂²u/∂t²·λ`，即函数真正返回 `dJ/dv`，线搜索相应改为减号更新。此前的符号与更新方向**恰好互相抵消**，所以流水线能跑通、误差正常下降——只有把「返回值」与「函数名/文档」三者对齐才能发现。判据是方向导数：沿单位梯度方向实测 `(J(v+εu) − J(v−εu))/(2ε) = +1.542e−16`（误差上升），必须与 `⟨g,u⟩` 同号；在 1 / 20 / 60 / 150 m/s 五个尺度上稳定成立。原先 `−(2/v)` 给出的是下降方向（`run_fwi` 用 `+` 号沿它走），与文档声明的公式矛盾。
- **线搜索**：固定步长是此前每阶段误差反而上升的直接原因；改为在真实 misfit 上回溯，并按接受比例调节步长上限。
- **held-out 炮完全不参与梯度**（`Survey.held_out` / `fit_shots`），且起始值与终值用**同一子波**评估——子波在反演中被刷新，用不同子波算的两个数不是同一个问题的 misfit，其差值可能是进步也可能是换了震源。
- `simulations/fwi_submission.py`（新增）：写出赛题要求的 `velocity_model.npy` / `wavelet.npy` / `run_summary.json`，写完立即读回校验；`score_model` 在提供真值时计算**去除每个深度水平均值后的横向相关系数**（该指标下纯深度趋势起点模型恒为 0），并把起点模型的值并列写出。没有真值时相关字段为**显式 null** 而非 0——两者在 JSON 里含义不同。
- 节点 `SeismicSurveyNode` / `SeismicForwardNode` / `FWIInversionNode` / `SeismicSubmissionNode`；`workflows/09_seismic_fwi.json` 端到端实跑通过。
- `tests/check_fwi.py`（新增）：正演稳定性、子波恢复精度、梯度方向（**沿梯度自身的下降曲线**——单方向有限差分低于 misfit 的 float64 噪声底）、误差下降 + 横向结构恢复，共 16 项。`tests/test_v07_3_seismic_fwi.py`（新增）19 项回归。

**硬碳预脱溶剂机理（Nat. Commun. 15, 3497 (2024)）**
- `models/desolvation.py` 与 `nodes/instruments/desolvation.py`：尺寸筛分 / 静置老化 / 双 SEI 能量学三个节点。
- 引擎数值精确对标论文：CIP / AGG 过孔能垒误差 0.00000 eV，静置阻抗在 4 h / 40 h 两点精确命中（86.200 / 14.600 Ω），活化能取原值，LUMO 位移为平台补充的库仑屏蔽估算（论文断言但未给计算）。
- `PreDesolvationMechanismNode`（新增）：把三条支路接成一条证据链，并**检查三者是否自洽**。三个独立标定的代理模型即便互相矛盾也各自画得像模像样，说出来比画出来更有用。**未连线（`not_connected`）与上游列名被改（`schema_mismatch`）分别报告**——两者都让用户去查连线，但真正要改的地方不同。
- `workflows/08_hard_carbon_predesolvation.json` 由三个孤立节点改为 4 节点 / 3 边的连通链路，整链实跑 `completed`，三条判据全 `ok`。
- `tests/test_v07_3_hard_carbon.py`（新增）21 项回归。

**API Key 管理与图形入口**

**Agent 工具守卫（借鉴腾讯开源 Octop）**
- `agent_runtime/tool_guard.py`（新增）：借鉴 [Octop](https://github.com/TencentCloud/Octop) 的 `tool_guard` 设计——**所有入口共用一个判定点**，工具调用在执行**之前**分类，而不是事后记录。Octop 是多用户服务、带交互式审批 UI；本项目是单用户桌面工作流，没有第二方来审批，所以 `approval` 在此表示「调用方必须显式传 `approved=True`」，Agent 节点把它作为明确拒绝上报。**不伪造一个审批对话框**，那比直接说不行更糟。
- 判定分三档 `allow` / `approval` / `deny` 而非布尔值：读与删不是同一个决定，压成布尔只会逼调用方自己重新区分。
- 规则是数据（`config/tool_guard.json`），用户可自行编辑而不必读 Python。**首条匹配胜出**——用户把规则加在文件开头就是要覆盖内置默认，「最specific 优先」会静默忽略它。**无匹配即拒绝**，用户策略文件若恰好没有兜底规则，必须失败关闭而不是失败打开。
- 已接入 `agent_runtime/tasks.py`：规划完成后判定，被拒节点**直接让任务失败**（`status: refused`），而不是记一条「denied」然后照常执行——后者比没有守卫更糟。
- 对全部 99 个已注册节点验证过分类结果：96 个只读计算节点放行，`ExportNode` / `ReportExportNode` / `SeismicSubmissionNode` 落入需审批。
- 规则按**真实类名**核对而非凭直觉：`*Submit*` 匹配不到 `Submission`（s-u-b-m-i-s-s-i-o-n），这条"看起来对"的规则实际上匹配为空，会让覆盖赛题产物的节点无人看守地运行。改为 `*Submission*`，并加测试遍历注册表，确保没有规则再次变成死策略。
- 没有对应节点的类别规则（`*Controlled*` / `*Delete*` / `*Upload*` / `*Write*` / `*.export*`）显式标注 `forward_looking=True`——前瞻性策略是合理的，「看着对但匹配为空」不是。
- `tests/test_v07_3_tool_guard.py`（新增）22 项回归。

- `ai_runtime/credentials.py`（新增）：9 家服务商的密钥存储，顺序为**系统密钥环 → 本地文件**（`config/credentials.json`，已 gitignore）。`list_credentials` / `set_credential` / `delete_credential` / `test_credential` / `mask_secret` / `credential_backend`。
- 保存时同步写进 `os.environ`——供应商读的是环境变量，只落盘会让界面显示「已配置」而运行时仍在离线降级。
- `backend/routers/credentials.py`（新增）5 个端点；写入类路由显式声明 `write` / `execute` 权限。
- GUI：`ApiKeyPanel`（右侧「密钥」标签页）+ **顶栏常驻徽标**（未配置时琥珀色并显示计数）+ 左侧图标栏钥匙按钮（无密钥时带提示点）。三处入口都直接打开该面板。
- **接口与界面都只返回掩码**（`sk-a•••••3456`，≤8 字符全掩），没有「显示明文」按钮，因为后端根本不会发送。
- 「已保存」不等于「可用」：测试连接是独立的一等按钮，走真实 HTTP 探测；服务商拒绝密钥返回 200 + `ok: false`（这是要显示的答案，不是传输错误），只有未知服务商才是 404。
- 存储位置写在面板顶部；无密钥环时明确告知密钥将明文保存，而不是让用户以为已被系统加密。
- `tests/test_v07_3_credentials.py`（新增）31 项回归，含「响应体全文搜索不得出现明文」与 GUI 入口的静态检查。

### 修复 Fixed

以下 12 项来自发布前对 0.7.3 新增代码的两轮独立审查，全部已修复并有回归测试。

- **无 OS 密钥环时密钥从不落盘，且谎报存储位置**：`set_credential` 的文件回退接在「keyring 存在但写入失败」的分支上，于是「根本没有 keyring」——正是桌面版的情况——密钥只存在于当前进程的 `os.environ`，`stored_in` 却仍报 `environment`，`list_credentials` 的告警还宣称密钥保存在 `config/credentials.json`，而那个文件并不存在。界面显示「已配置」、重启即丢、AI 运行时静默降级。已把回退判断改为「keyring 是否可用」。
- **`delete_credential` 会删掉用户自己 export 的环境变量**：无条件 `os.environ.pop`。现只清除本进程经 `set_credential` 写入的变量；继承自 shell 的保留，并在返回值中以 `shell_env_preserved` 告知调用方——否则「已删除」会被理解成「该服务商不可用」。
- **连通性探测的兜底分支会把供应商错误原文回显给浏览器**：401/403/404/429 都有专门的不回显分支，但 400/402 等状态直接把 `error.message` 拼进 `detail`，而多个供应商会在其中原文引用用户提交的密钥。现统一脱敏。
- **`agent_runtime/tasks.py` 的 `except KeyError` 是死分支**：`registry.get()` 抛的是 `NodeNotFoundError`（MRO 为 `NodeNotFoundError → ChemMLError → Exception`，并非 `KeyError` 子类）。LLM 规划器不校验节点目录，幻觉节点走到这里会炸掉整个规划阶段，用户看到的是与真实原因无关的错误。已改为同时捕获。
- **工具守卫漏掉 25 个高危节点**：`requires_external_software`（9 个，ORCA/VASP/GROMACS/LAMMPS…）与 `requires_network`（15 个，PubChem/PDB/LLM…）此前全部判为 `allow`，尽管模块文档承诺「凡是 shell out 或联网都需要显式决策」。改为按**能力**而非类名匹配，新增节点自动继承判定。判定从 3 个 `approval` 增至 28 个。
- **`get_guard()` 用相对路径读策略文件**：从仓库外启动后端时，用户写在 `config/tool_guard.json` 里的规则被静默忽略，退回默认策略。改为锚定仓库根。
- **首效曲线的饱和值被硬编码成 100 %**：`aging_curves` 把「孔填充期间形成的损失」与「填满后仍然存在的损失」折成了一个参数，于是老化到极限的电池报出 100 % 首效——一个论文从未测到、实验也做不出的数字。现拆为 `sei_capacity_loss`（老化期）与 `residual_loss_percent`（满孔残余，默认 `100 − ICE_AT_10D`）。
- **「锚定 12 h 的 90.14 %」实际上把它放在了 t = 0**：曲线是 `ICE(t) = plateau − sei_loss·exp(−t/τ)`，节点文案与工作流都按 `plateau − ICE_AT_12H = 8.95` 设参，而正确值是 `16.1781`（差 `1/exp(−12/τ)` ≈ 1.8 倍），且测试断言 `ice_percent[0]` 等于 12 h 的值，把这个偏差固化了。现由 `sei_loss_for_12h()` 派生，工作流与测试都用它。四个论文锚点（86.20 Ω / 14.60 Ω / 90.14 % / 99.09 %）现在全部精确命中。
- **老化表的时间栅格跳过了论文的实测时刻**：25 点均匀分布在 240 h 上步长为 10 h，恰好落在 12 h 与 40 h 之间，用户看到的表从未显示它声称复现的数值。改为在均匀栅格上并入 4 h / 12 h / 40 h / 末端四个锚点。
- **`write_submission` 在无上游反演时把 misfit 写成 `0.0`**：`FWIResult` 的 dataclass 默认值是 `0.0`，无法表达「未测量」，而提交节点恰好绕过 `to_dict()` 直接读字段，于是 `run_summary.json` 会出现 `initial: 0.0, final: 0.0`，读起来像完美拟合。字段改为 `Optional[float] = None`，三处写入点统一为 `null`。
- **汇总节点把两条不同量纲的曲线插值到同一横轴**：老化曲线以小时为轴、筛分曲线以埃为轴，重采样等于编造数据；原有的「行数不同就丢弃」判据恰好在两者行数**相同**时失效，而这正是用户裁剪某条支路后最常见的配置。改为各自成图（新增 `sieving` 输出端口），并删除已无调用者的 `_resample`。
- **`tests/check_fwi.py` 的 misfit 口径与被检验的梯度不一致**：只滤波建模、不滤波观测，测的是**另一个目标函数**的导数。这正是伴随梯度符号反了却仍然全绿的直接原因——两个 bug 互相抵消。现两侧同窗，脚本对未修复的符号会真实失败。另修正沿 `+grad` 走的方向（应当沿 `−grad` 下降），并把跨越两个倾斜界面的单块有限差分换成层内子块。

其余修复（首效饱和、列位置索引、`credentials.py` 重复赋值与注释、`version.py` 只检查不写入、监控 misfit 口径、子波刷新阈值）见下方历史条目。

- `ai_runtime/credentials.py`：`delete_credential` 的注释与实现不符，已改为描述真实行为。
- `scripts/version.py`：`TEXT_TARGETS`（README 标题、本地安装说明、requirements 头部、Python SDK README）与 `DESCRIPTION_TARGETS`（package.json description）此前**只被检查、从未被写入**——`--check` 报出漂移，`--write` 却输出「stamped 0 artefact(s)」。现已补上写入路径。
- 引擎监控 misfit 曾用**已滤波的建模减去未滤波的观测**，与梯度实际优化的目标不是同一个函数；现两侧用同一零相位窗。
- 子波刷新阈值原先与一个在本分支内被重新赋值的变量比较，导致每次读数恒为 0、此后不再刷新。
- **`_sponge` 的深部渐变方向与注释相反**：实际是「上强下弱」，最深行阻尼为零。之所以没出问题，是因为最深行被边界条件恒置为零——即阻尼方向是**偶然**正确的，一旦边界不再置零就成为反射体。已改为最深行阻尼最强。
- 死代码清理：`nodes/instruments/seismic.py` 的 `json` / `build_survey` / `lateral_correlation` / `SubmissionPaths` 未使用导入，`simulations/fwi_submission.py` 的 `List`，`models/desolvation.py` 中被立即覆盖的 `debye_a` 与重复赋值的 `rc`，`FWIConfig.max_courant_steps`（全仓库无读取处）。

### 变更 Changed

- 端口类型新增不透明的 `Survey`，用于在图上传递采集对象；`Survey` 刻意**不**做成 `ScientificObject`——三维道集检查器无法渲染，把每条道都记进运行输出会淹没结果；节点另行发布人可查看的道集、深度趋势与反演产物。
- `nodes/instruments/__init__.py` 导出四个地震节点与机制汇总节点；节点总数 99。

## [0.7.2] — 2026-10

**可信交付基线版本（Trusted Delivery Release）。** 在 v0.7.1 基础上**不新增大规模科研节点、不重构 Agent**；保持 0.7.2 版本号不变的前提下，按用户要求对前端做了一次 ComfyUI 风格整体重构（中英双语界面、三套视觉主题、节点双语），详见下方「UI 重构」小节。安全边界统一、桌面运行时方案落地、测试数字可复现、版本与产物互相追溯、科研节点如实声明执行来源、合成基准不冒充真实验证。

### 新增 Added

**统一安全策略（任务 P0-01）**
- `backend/ws_auth.py`（新增）：纯函数式 WebSocket 握手判定——`HandshakeDecision` / `extract_token` / `select_subprotocol` / `authorize_handshake`，与 HTTP 侧共用同一套 principal 与权限模型。
- `backend/run_registry.py`（新增）：运行级归属登记（`run_id → owner`）。**持有合法令牌不等于可以订阅任意运行**；`may_subscribe()` 区分 `foreign_run` 与 `unknown_run`。
- 令牌来源按优先级：`Sec-WebSocket-Protocol: chemml.token.<token>`（首选，accept 时回显）→ `X-ChemML-Token` → `?token=`（兼容，不推荐）。
- 应用私有关闭码：`4401` 未认证 / `4403` 越权 / `4408` 令牌过期 / `4400` 策略拒绝；拒绝时**先 accept 再发错误帧**，浏览器才拿得到原因。
- `backend/security.py`：新增 `identify()` / `authorize() -> (bool, reason)` / `origin_allowed()`；机器可读拒绝原因 8 种；`CHEMML_ENV=release` 时 `fail_closed`（无令牌即拒绝）且 `/api/docs`、`/api/redoc`、`/api/openapi.json`、`/api/ws/sessions` 不注册。
- 审计日志 `output/security_audit.jsonl`：记录 method / path / permission / outcome / reason / client / transport，**从不写入凭证**。

**测试是发布阻断项（任务 P0-03）**
- `pytest.ini`：登记 `unit` / `integration` / `security` / `benchmark` / `desktop` 五类标记与统一收集规则。
- `scripts/quality_gate.py`：每个门禁步骤输出 Git commit、Python 与关键依赖版本、实际命令、收集数、通过/失败/跳过/错误、退出码与日志路径；**超时是独立状态 `TIMEOUT`，永不折算成 PASS**。
- `scripts/ci_pipeline.py`（新增）：把发布流水线拆成 12 个独立阶段，逐阶段独立退出码；**任何子进程失败都不会被汇总脚本渲染成成功**。
- `.github/workflows/ci.yml`：接入阶段化流水线并归档每个阶段的日志与报告。

**统一版本与产物追溯（任务 P0-04）**
- `chemml_version.py`（新增）：唯一的版本来源（`__version__` / `__codename__` / `git_commit()` / `build_metadata()`）。后端、注册表、前端、Electron、工作流 JSON、发布脚本全部从这里读取。
- `scripts/version.py`（新增）：`--check` 在版本漂移时退出 1；`--write` 回写机器可改的产物；`--show` 打印版本与 commit。
- `scripts/release_manifest.py`（新增）：产出 `docs/RELEASE_MANIFEST.json` / `.md` 与 `SHA256SUMS`，为每个产物记录 commit、构建时间、SHA-256，并**显式区分已构建 / 已测试 / 已发布 / 未完成**。
- `docs/VERSIONING.md`（新增）：版本管理规范。

**科研节点执行来源与能力边界（任务 P0-05）**
- 每个节点声明 `capability_status`（verified / executable / experimental / unavailable）、`execution_mode`（external / internal_approximation / synthetic_demo）、`required_dependencies`、`input_constraints`、`validation_evidence`、`limitations`、`reproducibility_level`。
- **诚实降级规则**：声明 `verified` 却没有 `validation_evidence` → 自动降级为 `executable` 并附 `capability_status_note`；声明 `external` 却没有具名依赖 → 自动降级为 `internal_approximation`。注册表校验器同样会因此判定记录非法。
- `workflow_engine/node_base.py`：新增 `DependencyMissingError` 与 `require_dependencies()`——外部程序缺失时**拒绝执行**，而不是悄悄退化成内置近似。
- 已知答案回归测试 `tests/test_v07_2_node_known_answers.py`：注入高斯峰 → 峰位/峰高精确、max 归一化精确、线性斜坡平滑不变性、乙醇 C2H6O / 46.0419 / 3 重原子。

**合成基准与真实验证分离（任务 P0-06）**
- `docs/V07_2_SYNTHETIC_BENCHMARK.md`：把可执行基准明确命名为 **synthetic benchmark**，标注数据来源、生成方式、数据集版本、每个指标的定义与样本数。
- 回归阈值与对外宣传指标分开表述；**真实数据验证明确标记为「未完成」**，并给出设计文档 `docs/V07_2_REAL_DATA_VALIDATION_PLAN.md`。

### 变更 Changed

- `desktop/package.json`、`frontend/package.json`、`workflows/*.json`、README、本地安装说明、requirements 头部版本统一由 `chemml_version.py` 派生。
- `node_registry/scanner.py` 记录并汇总全部溯源字段；`validator.py` 新增 `_validate_provenance()`，把「无证据的 verified 声明」判为非法记录。
- `scripts/node_catalog.py` 输出能力状态、执行模式、可复现级别与证据计数，并明确警告 `internal_approximation` / `synthetic_demo` 结果不得当作第三方真实计算。

### 修复 Fixed

- `POST /api/workflows/run`（内联运行）在 v0.7.1 中**未被归类为 execute 权限**（`.+` 规则只匹配 `/api/workflows/<name>/run`），只读令牌因此可以触发工作流执行。已补显式路由规则。
- HTTP `GET /api/runs/{run_id}/events` 与 `GET /api/runs/{run_id}` 在 v0.7.1 中**没有任何运行级授权**；若不放行，新增的 WebSocket 运行级检查只是装饰。已改为统一 `may_subscribe()`，越权返回 403，未知运行返回一致的 404（不泄露运行是否存在）。
- `provenance` 的 `output_digests` / `output_artifacts` 字段自 v0.7 起**声明但从未被填充**（恒为空字典）。字段存在却不承载证据比没有字段更具误导性；现已由引擎逐节点写入。
- `DependencyMissingError` 的构造签名与 `require_dependencies()` 的调用方式不一致（`NodeExecutionError.__init__() missing 2 required positional arguments`），依赖缺失时抛的是 `TypeError` 而非可读的依赖错误。
- `chemml_version.git_commit()` 把 `HEAD` 误写为 `"--short" if short else "HEAD"` 的替换目标，导致 commit 恒为 `unknown`。
- `desktop/src/runtime-probe.js`：`outOfRange()` 用三位版本号与两位边界比较，把 3.13.14 误判为超出「3.10–3.13」范围。
- `desktop/src/runtime-probe.js`：改用异步 `spawn`（`spawnSync` 在受限主机上以 `EBUSY` 失败，且会阻塞 Electron 主进程）。
- `scripts/ci_pipeline.py` 以 `importlib` 执行质量门模块时未注册到 `sys.modules`，`@dataclass` 因此抛出 `AttributeError: 'NoneType' object has no attribute '__dict__'`，整个 CI 流水线无法启动。
- `scripts/quality_gate.py` 漏 `import shutil`，桌面运行时探针阶段以 `NameError` 失败。
- 质量门桌面探针阶段原先在 JSON 解析失败时仍返回 **PASS**（日志尾部的 `# exit=N` 使 `json.loads` 失败），即「未读到结论却报告成功」。现改为 ERROR 并用大括号配对提取载荷。
- 质量门 pytest 阶段从记录命令中剥离 `--basetemp` 时假设其为独立 argv 项，实际形如 `--basetemp=<path>`，导致 6 个阶段 `ValueError`。
- `requirements.txt` 只含 `-r` 引用行，许可证报告把它当作包名解析（出现名为 `-r requirements.runtime.txt` 的「依赖」）；现按 `-r` 展开并只对**必需**依赖判失败。
- `scripts/license_report.py` 的 `main()` 在 `--check` 下**仍然写盘**，即「校验」会悄悄修好它本该发现的问题；且 `docs/THIRD_PARTY_LICENSES.md` 第 5 节按本机 `frontend/dist` 状态分支输出、第 6 节输出清洁度扫描命中条数，导致该文档（其 SHA-256 被发布清单固定）**随本机构建产物变化**，同一次门禁内记录值与重算值必然不等。现改为 `--check` 只比对不写盘、漂移即阻断，并让文档只陈述与发布包和锁定依赖图有关的政策；回归测试 `test_document_does_not_depend_on_the_local_build_output` 锁死该性质。
- 发布清单先前把门禁自己产出的报告（gate / CI / 复现报告）也按内容哈希固定，导致检查**必然自失败**；现为这类产物标记 `volatile` 并按存在性比对，非易变产物（安装包、SBOM、NOTICE、许可证清单、锁文件）仍逐字节比对。
- `docs/RELEASE_MANIFEST.json` / `SHA256SUMS` 是**发布构建步骤的输出**：清单无法记录包含它自身的提交哈希，因此流程为「先提交源码 → 再生成清单」，`--check` 会同时比对版本、commit 与逐产物身份/哈希。
- `.gitignore` 未覆盖 vite 在加载 `vite.config.ts` 时写出的 `frontend/vite.config.ts.timestamp-*.mjs` 临时文件，该文件在无法删除临时文件的受限主机上会残留并被误提交；现加入忽略规则。

### 修复 Fixed（tag 后交付收尾，ISSUE-18…26）

tag `v0.7.2` 通过全部门禁后，按「先本地安装实测、再宣称可交付」完成真实安装运行，又修复 9 个问题（完整记录见 `docs/V07_2_ISSUE_LOG.md`）：

- **P0**：桌面安装包**从来无法启动**——`backend/app.py` 导入 `chemml_version`，而该模块不在 `extraResources` 中，`resources/app/` 缺文件即 `ImportError`；electron-builder 只打包不运行，故构建"成功"。已补 `extraResources` 并重建安装包；桌面测试由 21 项增至 35 项，且**真正导入打包布局内的后端**（此前全部只读配置）。
- **P0**：`SHA256SUMS` 曾被打进它校验的归档内，形成自指循环；现排除出包、随包旁发布，并有回归测试锁死。
- 版本一致性检查覆盖不全：启动横幅 `v0.6.0`、标签标题 `v0.7.1`、86 个节点 `0.7.1` 与"检查通过"并存；`scripts/version.py` 扩展覆盖面并修复 `CHANGELOG.md` 缺失时崩溃。
- 解压出的副本无法自报构建提交：`scripts/package.py` 向归档注入 `BUILD_INFO.json`，`chemml_version` 增加回退链，桌面壳 payload 由 `scripts/refresh_desktop_payload.py` 盖同一印章。
- 溯源造假防护：`git rev-parse` 会应答任意祖先仓库，`chemml_version` 现只在本树根**本身就是** Git 顶层时采信 Git，否则回退印章、再否则 `unknown`；重新打包无 Git 副本时向前继承原印章。
- 桌面壳前端回退路径与打包产物位置不一致（回退永不生效）；文档声称启动脚本注入会话令牌（实际仅桌面壳注入）；测试残留 `workspace/raw_data/x.csv` 随源码包发布。
- **构建印章进入构建本身**（`desktop/scripts/stamp-build-info.js`，beforeBuild 钩子）：Electron 构建与源码归档现在由同一套 `chemml_version.build_stamp()` 代码盖章，字段一致；钩子以模块路径接入 electron-builder，缺失 Python 解释器时只警告不失败。
- **CI 与文档化的发布构建对齐**：第 10 阶段补上 `-c.win.signAndEditExecutable=false`（本机无证书，免签名是既定发布路径）；第 3/4/5 阶段改用 per-run `--basetemp`，不再因加固宿主的临时目录回收钩子把「全部通过」渲染成退出码 1。
- **载荷刷新收敛**（ISSUE-25）：刷新工具的拷贝循环曾把树根钩子印章盖回载荷、印章逻辑再改写，两步互相覆盖——每轮恒定 2 个伪更新、永不收敛；现拷贝循环跳过 `app/BUILD_INFO.json`（印章是生成的，不是拷贝的），回归测试锁死「预置陌生提交的印章也必须第二次收敛」。
- **门禁计数口径**（ISSUE-26）：`python_compile` 阶段的「一级源码文件数」把桌面 payload 测试留在 `output/pytest_gate_tmp/` 下的整树夹具也计了进去——同一棵树逐轮报出 2663 → 3479 → 4296，真实值 211。现计数与 `compileall` 跳过范围从同一集合生成（新增 `output` / `workspace` / `.pytest_cache` 等运行期目录），并用 3 项回归测试锁死。
- 测试总数 385 → **413**；门禁 27 阶段保持 `pass=26 fail=0 skip=1`，安装包与源码归档均带构建印章且互相可追溯。

### 新增 Added（续）

**科研结果溯源与复现（任务 P1-06）**
- 运行级溯源新增：`platform`（版本 / 代号 / commit）、`workflow`（定义 SHA-256、节点数、边数）、`max_workers`、`resource_usage`、`execution_modes` 普查、`reproducibility` 结论、`environment.key_dependencies`（数值关键依赖版本）。
- 逐节点新增：`execution_mode` 与 `capability_status`（**实际**执行的模式，而非类声明）、`output_digests`（逐端口科学内容摘要）、`output_artifacts`（产物路径 + 文件字节 SHA-256）。
- 摘要口径明确定义并写入记录：剔除运行期身份字段（`VOLATILE_DIGEST_KEYS`）与形如 `run_8ef77927` 的自动生成 id（`GENERATED_ID_RE`），并归一化运行 id / 运行目录字面量。判定依据刻意选**值形状**而非 `*_id` 键名，以免连带丢弃 `dataset_id` 这类有科学含义的标识。
- `scripts/verify_reproducibility.py`（新增）：重复运行同一工作流并逐节点比对输出摘要；**只有事先声明为非确定性或未固定种子的节点才被豁免**，静默不稳定判为失败；退出码 1 表示存在无法解释的差异。
- `reproducibility()` 明确拒绝绝对承诺，只声明「声明为 deterministic 且已固定随机种子的节点」；`claim` 字段写入拒绝语，`digest_scope` 说明摘要覆盖与排除范围。
- `docs/V07_2_PLUGIN_SPEC.md`（新增）：插件与外部程序执行边界规范（P1-03 / P2-04），含 `ControlledRunner` 白名单、参数列表与 `shell=False`、超时与清理，以及**明确列为「未实现」**的沙箱能力清单。
- `tests/test_v07_1_capabilities.py` 补两项超时用例：子进程心跳计数在超时后停止增长（证明进程确被终止，而非仅抛异常）与超时后 scratch 目录被清理。
- 质量门新增 `reproducibility_verification` 阶段；CI 第 6 阶段支持**多命令独立记录**（每条命令各自退出码与日志），任一失败即否决该阶段。

### 新增 Added（UI 重构：ComfyUI 框架 + 中英双语 + 双主题）

> 版本号保持 **0.7.2** 不变。按用户要求对前端做整体重构，使其框架结构与视觉语言对齐 ComfyUI，并支持界面中英切换、节点中英双语、WorkBuddy 白/黑双主题。

- **框架结构（ComfyUI 风格）**：`App.tsx` 重写为「顶栏 + 左侧可折叠图标轨 + 中央画布 + 右侧 Dock + 底部运行条」五区布局。新增 `components/TopBar.tsx`（工作流/编辑/帮助菜单 + 工作流标题 + 主题/语言切换 + 桌面窗口控制）、`components/IconRail.tsx`（节点库/示例/数据/AI/助手/模拟/控制台抽屉入口）、`components/BottomBar.tsx`（运行 + 队列数 + 状态）、`components/Drawer.tsx`（可复用抽屉）、`components/AboutDialog.tsx`；旧 `Toolbar.tsx` 退役。
- **双视觉主题**：`theme.ts` 导出 `wb-light`（WorkBuddy 白）与 `wb-dark`（WorkBuddy 黑）两套令牌，运行时写入 CSS 变量并持久化 `localStorage`，**首次启动默认 WorkBuddy 黑**，此后沿用用户上次选择；`tailwind.config.js` 语义色统一映射到 `rgb(var(--c-*) / <alpha-value>)`；`index.css` 的 React Flow 覆写、滚动条、节点卡片全部改用变量；支持 `?theme=` / `?lang=` / `?workflow=` 深链。
- **节点中英双语**：新增根级数据层 `node_i18n.py`，为 89 个节点提供中文名、28 个分类中文名、节点/参数/端口的英文描述与枚举选项英中文标签；`workflow_engine/node_base.py::spec()` 出口统一注入 `name_zh` / `category_zh` / `description_en` / 参数与端口 `description_en` / `options_en`，`node_registry/scanner.py` 同写 `registry.json`。
- **界面文案双语化**：`i18n.ts` 补齐全部界面键位，支持 `?lang=zh|en` 深链；`NodePalette` / `Inspector` / `Dock` / `Marketplace` / `AIPanel` / `AgentPanel` / `Console` 全部接入双语标签，6 个 `workflows/*.json` 演示工作流补充 `label_en`。
- **节点卡片重写**：`nodes/ScientificNodeCard.tsx` 改为 ComfyUI 风格——分类着色头部、节点内嵌参数控件（下拉/数字/文本/布尔）、按数据类型着色的输入输出端口（连线同色并带动画）、中英标题与描述切换。
- **谱图绘制面板**：新增 `panels/PlotPanel.tsx` 与 `spectra.ts`（从运行记录提取谱图序列），右侧 Dock 增加「谱图」标签；按数据类型分别绘制——质谱为棒状图（stick plot）并列出主要峰，其余谱图为线图；工作流运行结束后自动切到该标签。
- **产物窗口（ComfyUI 式输出抽屉）**：新增 `panels/OutputPanel.tsx`——状态徽标、运行 ID、**可读耗时**（`176 ms` / `6.61 s` / `2m 05s`，替换原先直接显示原始毫秒）、`完成/总数 节点` 与失败计数、逐节点进度条与展开的错误全文/日志、产物文件可下载链接；运行时秒表实时计时且进度条**保持不确定态**（内联接口整图跑完才返回，不伪造百分比）。**每次运行自动展开**，失败不会再被折叠的控制台吞掉。底栏新增带状态徽标的「产物」开关按钮。
- **布局对齐 ComfyUI**：右侧 Dock 可折叠为边缘把手（画布因此获得整个窗口宽度）、Dock 宽度响应式（`w-72`→`xl:w-80`）、小地图上移让出右下角给浮动运行条（此前两者重叠、缩放按钮点不到）。
- **mzML 质谱完整工作流**：新增 `workflows/07_mzml_mass_spec_analysis.json`（添加文件 → 峰提取 → 未知物鉴定 + AI agent 分析 → AI agent 生成鉴定报告），示例数据 `datasets/mass_spectrometry/scan_018081.mzml` 及配套元数据一并登记（`scripts/dataset_governance.py` 覆盖 10/10）。

### 修复 Fixed（UI 重构收尾 + 质谱链路）

- `desktop/package.json` 的 `extraResources` 漏收新增根级模块 `node_i18n.py`，导致 `test_every_root_level_module_is_packaged` 失败；已补收并复跑桌面测试 35 项全过。
- **mzML 解析器无法读取任何真实文件**：`workflow_engine/parsers/mzml.py::_decode_binary` 使用 numpy 风格的 `<f8` / `<i4` 格式串，`struct` 不接受 `<` 前缀（`struct.calcsize` 直接抛异常），且 `_parse_spectrum` 只在 `binaryDataArray` 上直查 `cvParam`，未解析 `referenceableParamGroupRef`，导致精度/压缩参数丢失。已修正为合法的 `<f`、`>i` 等格式串并支持引用组。
- **无 PyTorch 主机上所有工作流整体崩溃**（用户实测报「运行出错」）：`provenance/schema.py::collect_environment` 的 `except Exception:` 分支里**又引用了 `torch`**，而 import 失败时该名字根本未绑定 → `UnboundLocalError: cannot access local variable 'torch'`，在第一个节点执行前抛出。桌面版用宿主机自带 Python（本机 `D://python 3.13.6` 无 torch）因此必然踩中，而开发 venv 有 torch 所以测试全绿。现已删除该多余分支（它同时是**第二个重复 `except Exception`**，属坏补丁指纹），并加 `tests/test_v07_2_no_torch_host.py`：模拟无 torch 主机 + 静态禁止任何 `except` 分支引用 `torch` + 全仓扫描重复 `except`。已在 `D://python 3.13.6`（真实无 torch 解释器）上验证整条 mzML 工作流 6/6 通过。
- **失败在界面上不可见**：运行出错只写进默认折叠的控制台抽屉，用户看到的是「什么都没发生」。新增产物窗口（见下），并改为每次运行自动展开。
- **产物下载链接点开即 404**：`_relative_artifacts` 用 `str(Path(...))` 生成路径，Windows 上是反斜杠，浏览器拿到 `output\api_runs\runs\<id>\artifacts\x.html` 这种非法 URL 路径。已改为 `.as_posix()` 输出 POSIX 分隔符（`backend/routers/runs.py` 的运行列表同样修正），前端对每段做 `encodeURIComponent`。

- **`ScientificAgentNode` 子规划拿不到上游数据**：`nodes/agent/agent.py::_context_data` 按**节点类型**组织提示（如 `{"SpectrumFileNode": {"path": ...}}`），而规划器按 **data_key 名**（`path` / `smiles` / `formula`）取值，两者键名不一致，上游数据从未真正注入；此外单条边连入 `multi` 端口时引擎传入的是单个对象而非列表，可迭代的 Pydantic 模型被误当元素序列逐字段拆散。已统一为 data_key 键名、按 `ScientificObject`/列表/单对象三级归一化输入，并新增谱图 `metadata["source_file"]` 回退，使 agent 子工作流能读到真实文件。


### 已知限制 Known Limitations

- 真实仪器数据上的鉴定准确率**尚未验证**；现有基准全部是合成数据，见 `docs/V07_2_SYNTHETIC_BENCHMARK.md`。
- NSIS 安装包在非提权 Windows 构建机上**未签名**；本机受限离线构建路径跳过 exe 资源改写，因此使用 Electron 默认图标与元数据；安装包 SHA-256 见 `SHA256SUMS`。
- 桌面运行时采用**受控安装器（方案 B）**：不捆绑 Python 解释器，安装后首次启动由运行时探针检查系统 Python 与锁定依赖。见 `docs/V07_2_DESKTOP_RUNTIME.md`。
- 仅 Windows x64 完成构建与验证；Linux / macOS 目标已声明但**未验证**，不得视为正式支持。
- 本机受限沙箱下 `GetProcessMemoryInfo` 被拒，`resource_usage.peak_rss_bytes` 为 `null` 并附 `peak_rss_note`；墙钟时间与进程 CPU 时间仍可用。缺失指标如实标注为缺失，不以估算值填充。
- 插件**无操作系统级沙箱**（与后端同进程运行，可访问进程可读的文件与网络）。当前安全模型是「受信任插件 + 受控外部调用」，不是不可信插件沙箱；见 `docs/V07_2_PLUGIN_SPEC.md` §3.4。

## [0.7.1] — 2026-10

**安全整改、工程补齐、桌面交付与质量验证版本。** 在 v0.7.0 基础上**不删除任何已有功能**，目标是把 v0.7.0 从「功能覆盖较广的 Alpha 原型」提升为「可安装、可运行、可验证、可追溯、可维护的科研软件预览版」。**不以新增节点数量为核心指标**。

### 新增 Added

**流式上传与存储安全（任务 C / §P1-01、P1-09）**
- `storage/service.py`：新增 `save_upload_stream` / `UploadSession`——按块写入 `*.part` 临时文件，**边收边校验**字节上限与墙钟超时，通过后原子提交；超限即刻中止，绝不先整包读入内存。
- 并发上传上限（`max_concurrent_uploads`）与上传超时；中断/失败自动清理半成品文件。
- `backend/routers/storage.py`：上传接口由「整包读取再检查」改为流式转发。

**本地 API 认证与权限边界（任务 D / §P1-02、P1-03）**
- 新增 `backend/security.py`：`AuthMiddleware` 纯 ASGI 中间件 + 会话令牌（`X-ChemML-Token` / `Authorization: Bearer` / `?token=`）；权限四类 **read / write / execute / external**；只读令牌无法触达写入或执行路由；allow/deny 审计日志 `output/security_audit.jsonl`。
- `backend/app.py`：CORS 由 `allow_origins=["*"]` 改为**显式白名单**，最小方法/请求头；新增 `GET /api/security/status` 如实报告安全姿态（不泄露密钥）。
- 未配置令牌时保持回环开发模式，并**如实标注**为未启用认证。

**Agent 真实执行闭环（任务 B / §P0-03）**
- 新增 `agent_runtime/tasks.py`：`TaskScheduler` 统一驱动 `Plan → 审批 → 执行 → 验证 → 完成`；`AwaitingApproval / Failed / Cancelled` 异常路径；按节点能力推导所需权限与风险；幂等指纹防止同一任务重复提交；支持 approve / reject / cancel / retry（重试预算有限）。
- `backend/routers/agent.py`：`/api/agent/ask`、`/plan`、`/tasks`、`/tasks/{id}`、`approve`、`reject`、`cancel`、`retry`、`/history` 全部经状态机。
- `workflow_engine/engine.py`：协作式取消（`cancel()` + 取消事件），取消后停止后续调度并记录已完成 / 未完成步骤。

**节点能力标签与状态分级（任务 E / F / §P1-04、P1-05）**
- `workflow_engine/node_base.py`：新增 `capabilities`、`implementation_status`、`deterministic`、`required_software`；`spec()` 全量输出。
- 全库节点标注能力：`requires_network`（数据库 / LLM）、`requires_gpu`（GPU 节点）、`requires_external_software` + `experimental`（量子化学 / MD / 材料仿真连接器）、`writes_files`（导出 / 报告）、`sensitive_data`（LLM）、`nondeterministic`（训练 / 基准计时）。
- 新增 `node_registry/capabilities.py` + `scripts/node_catalog.py`：运行时探测生成 **状态分级**（unavailable 表示外部程序缺失，绝不伪造成功），产出 `docs/node-catalog.md` 能力目录。

**受控外部程序执行（任务 E / §E.2）**
- 新增 `simulations/controlled.py`：`TOOL_ALLOWLIST` 固定可执行文件白名单（ORCA / Gaussian / Psi4 / CP2K / GROMACS / LAMMPS / OpenMM / VASP / Quantum ESPRESSO）；`ControlledRunner` 以**显式 argv + `shell=False`** 调用，独立 scratch 工作目录，超时 / 输出上限 / 并发信号量，失败与取消自动清理；`describe_tools()` 输出外部软件兼容性报告。模型或插件生成的任意字符串**无法**作为 shell 命令执行。

**科学基准（任务 I / §P1-06）**
- 新增 `scripts/benchmark_lcms.py`：LC-MS/MS 已知答案基准，对 24 个已核验化合物 × **两套参考库**（闭环 `synthetic` / 跨来源 `curated`）评测 Top-1 / Top-3 / Top-5 命中率与 MRR，并附**阴性对照**（匹配-错配判别力、两次运行确定性、库外分析物开放集）。报告见 `docs/V07_1_BENCHMARK.md`，可经 `--strict` 纳入质量门禁。
- `nodes/question/identification.py`：外部候选库表（`candidates` 端口）现可解析碎片 / IR / Raman / UV 列表列，使 CSV 参考库能驱动全部证据通道。

**开源合规（任务 K / §P2-01、P2-02）**
- 新增 `scripts/license_report.py`：由**实际依赖元数据**生成 Python + 前端依赖许可清单（`docs/THIRD_PARTY_LICENSES.md`）、CycloneDX 1.5 SBOM（`sbom.json`）与根 `NOTICE`；许可证检查不再依赖硬编码列表。

**质量门禁与发布工程（任务 L / §P0-04、P0-05）**
- `scripts/quality_gate.py`：新增科学基准、许可 / SBOM、发布包清洁度、节点目录一致性、已发布产物版本一致性、Electron 安装包产物检查；许可检查改为读取真实依赖元数据；修正版本一致性检查（原先未真正读取后端 `VERSION`）。
- `scripts/node_catalog.py`：README 节点数与注册表一致性检查，杜绝文档漂移。
- `backend/app.py`：前端静态资源统一以 `frontend/dist` 为**唯一来源**（`static/` 仅作生成式回退），消除重复资源。
- 清理构建缓存（`*.pyc` / `__pycache__`），发布包经 `scripts/package.py` 规则验证不含缓存、密钥与运行时数据。

### 变更 Changed

- 版本号全面统一为 **0.7.1**（README / CHANGELOG / `desktop` / `frontend` / `requirements.txt` / `workflows/*.json` / 本地安装说明 / 后端 UA / registry 元数据）。
- `node_registry/registry.json` 重新生成：**89 节点 / 28 分类 / 52 模块**（此前登记的 85 / 27 / 50 已陈旧）。
- 报告导出补充溯源与证据分级章节（工作流 / 节点版本、参数、执行后端与降级、确定性、运行环境）及**结果局限**声明；`ReportExportNode` 新增 `docx` 格式（经 `report_engine` + `python-docx`，缺失时给出明确错误而非伪造文件）。

### 修复 Fixed

- 测试 `tests/test_v06.py::test_api_health_version` 的版本断言未包含 `0.7.1`。
- 质量门禁 `check_version_consistency` 未真正解析后端版本号。
- `scripts/package.py` 排除规则顺序缺陷：全局排除未先于 `memory/` 重包含，`memory/__pycache__/*.pyc` 可能入包。
- 质量门禁 pytest 子集在加固主机上因复用 `--basetemp` 触发宿主安全删除钩子（`OSError [Errno 123]`）而误报；改为每次调用使用全新 basetemp。

### 文档 Documentation

- 新增 `docs/V07_1_RELEASE_REPORT.md`（发布报告：任务 A–L 完成矩阵、真实验证数字、未完项）、`docs/V07_1_SECURITY_REPORT.md`（安全整改与权限测试）、`docs/V07_1_BENCHMARK.md`（已知答案基准）、`docs/THIRD_PARTY_LICENSES.md`（真实依赖许可清单）；`docs/README.md` 增补质量 / 验证 / 合规索引；`docs/V07_1_COMPLETENESS_AUDIT.md` 标注为整改前时点文档。

### 已知限制 Known Limitations

见 `docs/V07_KNOWN_LIMITATIONS.md`。v0.7.1 仍为**科研软件预览版（Hardened Preview，非 GA）**：外部科学软件连接器在未安装真实程序时标记为 `unavailable` / `experimental`，不得视为已验证集成；基座模型在缺少预训练权重时使用确定性投影近似（标记 `experimental`）；Windows NSIS 安装包**已产出**（`desktop/dist/`，未签名、默认图标），但**干净机安装测试与代码签名尚未完成**（构建机非管理员，`winCodeSign` 符号链接解压受限）。完整状态与未完项见 `docs/V07_1_RELEASE_REPORT.md`。

## [0.7.0 Desktop Scientific AI OS] — 2026-10

「桌面科研 AI OS」版：在 v0.6.0 基础上**不删除任何已有功能**，新增安全存储层、统一错误模型、全运行溯源、Agent 任务状态机、GPU/PyTorch 节点体系、三格式报告导出引擎、Electron 桌面外壳与质量门禁。测试从 62 项扩展到 **148 项**（7 项 GPU 测试按硬件可用性如实跳过/启用），六个官方 Demo 全部继续通过。

### 新增 Added

**安全存储层 `storage/`（规范 §8.2）**
- `storage/paths.py`：`safe_join` 用 `Path.resolve()` + `relative_to` 做根包含校验（拒绝 `..`、绝对路径、UNC、设备命名空间、symlink/junction 逃逸）；`sanitize_filename` 文件名消毒。
- `storage/service.py`：`StorageService` 原子写入（临时文件 + `os.replace`）、上传配额与 SHA-256 摘要、zip 解压三重防护（zip-slip / zip-bomb / 条目数与嵌套深度）。
- `storage/workspace.py`：`WorkspaceService` 八分类白名单工作区（raw_data/cache/workflows/models/runs/uploads/reports/records），分类间互相隔离。

**统一错误模型 `workflow_engine/error_model.py`（规范 §9）**
- 14 个规范错误码位（`VALIDATION_ERROR` … `CANCELLED`）、可恢复性判定、中文建议动作、出口统一密钥脱敏（sk-/Bearer/GitHub/JWT）。

**全运行溯源 `provenance/`（规范 §11）**
- `ProvenanceRecord` schema：输入摘要、节点版本、参数快照、provider/model、外部软件、环境快照、随机种子、缓存命中、fallback、设备、产物引用。
- 引擎集成：每次 `WorkflowEngine.run()` 结束自动写 `runs/<run_id>/provenance.json`（`RunResult.provenance_path`）。

**Agent 任务状态机 `workflow_engine/agent_state.py`（规范 §5.1）**
- `CREATED → PLANNING → WAITING_FOR_APPROVAL → RUNNING → VERIFYING → COMPLETED` 严格生命周期；`PAUSED`/`WAITING_FOR_INPUT`；非法转移拒绝；重试预算防无限重试；全程审计历史。

**GPU / PyTorch 节点 `nodes/gpu/`（规范 §7）**
- `GpuDeviceInfoNode`（真实探测 torch/CUDA/显存）、`PyTorchTensorOpNode`（种子确定性 + 诚实 CPU fallback 标注）、`ModelInferenceNode`、`InferenceBenchmarkNode`。GPU 不可用时明确报 `GPU_UNAVAILABLE` 并给出安装指引，绝不虚报加速。

**报告导出引擎 `report_engine/`（规范 §13）**
- Markdown / HTML（用户文本全量转义防注入）/ DOCX（python-docx）三格式导出，内容全部来自真实 `RunResult`；导出结果附大小 + SHA-256 完整性校验。

**安全文件 API `backend/routers/storage.py`（规范 §8, §22-C）**
- `POST /api/storage/upload/{category}`（文件名消毒 + 配额 + 格式探测 + 厂商格式警告）、`GET /api/storage/list/{category}`、`DELETE /api/storage/file/{category}/{path}`。
- 修复 `runs.py` 下载接口的字符串前缀比较漏洞，改为解析后根包含校验，且只允许访问已登记的产物根。

**Electron 桌面外壳 `desktop/`（规范 §3）**
- 主进程管理 Python 后端生命周期（spawn + `/api/health` 轮询 + 端口协商 + 退出清理进程树）、preload 安全 IPC、electron-builder Windows NSIS / Linux / macOS 配置。

**质量门禁 `scripts/quality_gate.py`（规范 §18）**
- 18 项检查（编译/测试/节点 Schema/工作流校验/Demo Dry Run/安全/报告/状态机/前端/版本一致性/乱码/凭据扫描/许可证/GPU 状态），输出 JSON + Markdown 双报告；SKIP 如实计数，不计入通过。

### 变更 Changed
- 节点基类新增 `capabilities` 能力标签（requires_network / requires_gpu / …），进入 `spec()` 供前端与权限提示使用。
- API 版本号升级为 `0.7.0`（`/api/health`、`/api/meta`）；`test_api_health_version` 兼容 0.6/0.7。

## [0.6.0 Scientific Foundation Model Edition] — 2026

「统一科学基座模型」版：在 v0.5.3 基础上**不删除任何已有功能**，把分散的编码器 / 预测器收敛为**一个注册表 + 五个稳定 API**，并补齐 Cloud/Local AI 切换、可运行 Agent、科学数据目录、仿真作业管理与选项卡工作台。**85 个科学节点 · 27 个分类 · 50 个模块 · 6 个官方 Demo · 62 项自动化测试**，全部版本号统一为 `0.6.0`。

### 新增 Added

**统一科学基座模型 `foundation/`**
- `foundation/base.py`：`FoundationModel` 基类（`key/name/family/modality/dimension/capabilities/properties/requires_weights`）、`FoundationRegistry`（`register/get/family/describe/embed/similarity/predict`）、确定性 `seed_vector`、`registry` 单例。
- `foundation/molecular.py`：ChemBERTa（384）· GROVER（512）· Graphormer（768）· Uni-Mol（512）· Morgan（2048）· Descriptor-Vector（18，真实描述符键）· Physchem 属性预测器（logp/esol/heavy_atoms …）。
- `foundation/spectral.py`：Spectrum-Bin（128 分箱）· Spectrum-Summary（8 特征），兼容 `Spectrum` / dict / `(x, y)` 三种输入。
- 对外 API：`embed`/`similarity`/`predict`/`describe`/`catalog`；`similarity` 支持 `cosine`（默认）与 `euclidean`。
- `nodes/ai/foundation.py` 重写为**薄适配器**：`ChemBERTaNode`/`GROVERNode`/`GraphormerNode`/`UniMolNode` 统一委托 `foundation/`，消除重复实现。

**Cloud / Local AI 切换 `ai_runtime/config.py`**
- `AIConfig(mode, provider, model, temperature, max_tokens, timeout, api_keys, base_urls)`；`mode ∈ {auto, cloud, local, open_source, chemistry, offline}`。
- 持久化到 `config/ai.json`；环境变量覆盖 `CHEMML_AI_MODE`；`family_order()` 始终把 `offline` 追加在末位，**任何模式都优雅降级**。
- 模板 `config/ai.example.json`；`.gitignore` 排除实际配置 `config/ai.json`。

**Agent 可运行**
- `nodes/agent/planner.py`：新增 `plan_with_llm(question, context, complete=None)`，规划器优先走 `ai_runtime.complete`，**拒绝 `family=="offline"` 的产物**并回退规则配方（记录回退说明）。
- `nodes/agent/agent.py`：`use_llm` 默认 `True`；新增 `run_question` / `plan_question` / `summarise` 便捷函数；报告元数据补充 `status` / `duration_ms` / `errors` / `records`。
- `scripts/run_agent.py`：命令行入口，支持位置参数 / `-q`、`--mode`、`--language`、`--no-llm`、`--max-nodes`、`--json`、`--out`。

**科学数据目录 `data_layer/catalog.py`**
- `DataCatalog`：`add/ingest/get/search/types/tags/stats/all/clear`，为分子（morgan）与谱图（spectrum-bin）生成基座嵌入，支持跨类型相似检索。
- 路径感知 `get_catalog(path=None)` + `_CATALOGS` 缓存；`CHEMML_CATALOG` 环境变量可重定向。

**仿真作业管理 `simulation_runtime/jobs.py`**
- `SimulationJob` 数据类 + `JobManager`（线程池）：`submit/run_now/list/get/stats`，包装 `runtime.run(family, system, backend)`。

**REST 路由器（`backend/routers/`）**
- `ai.py`：`/ai/modes` · `/ai/providers` · `/ai/config`（GET/PUT，密钥掩码）· `/ai/complete` · `/ai/test`。
- `agent.py`：`/agent/ask` · `/agent/plan` · `/agent/history`。
- `data.py`：`/data/catalog` · `/data/catalog/{id}` · `/data/stats` · `/data/ingest` · `/data/datasets`。
- `simulations.py`：`/simulations/families` · `/backends` · `/run` · `/jobs` · `/jobs/{id}`。
- `foundation.py`：`/foundation/models` · `/embed` · `/similarity` · `/predict`。

**GUI：选项卡式工作台 Dock**
- 右侧面板升级为 `Dock`（检查器 / AI / Agent / 数据 / 仿真五标签）；新增 `AIPanel` / `AgentPanel` / `DataPanel` / `SimulationPanel`。
- 工具栏新增 🤖 / ✦ / 🗄 / ⚛ 面板切换按钮；品牌名升级为 `v0.6.0 Foundation Model Edition`；i18n 新增约 50 个中英文键。
- `store.ts` 新增 `DockTab` 状态；`Inspector.tsx` 改为可嵌入 Dock 的容器。

**Demo 与文档**
- 新增 `workflows/06_scientific_foundation_models.json`（Molecule → ChemBERTa → Uni-Mol → 分子描述符 → Report Agent）。
- 新增 `docs/v0.6-task-spec.md`（任务书：范围、五大优先级、模块清单、验收标准、非目标）。

### 变更 Changed
- 全仓库版本号统一为 `0.6.0`（约 52 个文件：`__version__` / `version` / JSON `version` / Docker 镜像标签）。
- `scripts/package.py`：排除 `memory/*.json`（Agent 运行时记忆，会自动重建）、`config/ai.json`、`.tmp`；新增 `--name` 指定归档根目录。
- `backend/app.py`：注册 5 个新路由器，`/api/health` 与 `/api/meta` 版本号 → `0.6.0`。
- `node_registry/registry.json` 重新生成：85 节点 / 27 分类 / 50 模块，全部 `0.6.0`。
- 前端 `package.json` 版本 → `0.6.0`；`types.ts` / `api.ts` 新增基座模型、AI 配置、Agent、数据目录、仿真作业的类型与客户端方法。

### 修复 Fixed
- `ai_runtime/config.py`：`set_mode` / `set_provider` / `update_config` / `reset_config` 误返回路径（导致 `PUT /api/ai/config` 报 `WindowsPath has no attribute 'to_dict'`），改为返回 `AIConfig`。
- `scripts/run_agent.py`：报告章节为 dict 时 `heading` 属性访问失败，改用 `_section()` 归一化。
- `foundation/molecular.py`：修正不存在的描述符键（`NumHeavyAtoms` → `HeavyAtomCount` 等），`_VECTOR_KEYS` 收敛为 18 个真实键。
- `foundation/base.py`：清理 `similarity` 中的恒真分支，明确 cosine/euclidean 两条路径。
- `nodes/ai/foundation.py`：`smiles` 参数回退路径误触发「无输入」异常，改用 `first_of(..., required=False)`。
- `data_layer`：模块级单例忽略 `CHEMML_CATALOG`，新增路径感知 `get_catalog()`，REST 层按请求解析。
- `simulation_runtime/jobs.py`：简化 `_trim`，只保留最新历史作业，避免误删运行中作业。

### 新增测试 Added tests
- `tests/test_v06.py`：19 项，覆盖基座模型、AI 配置与切换、数据目录、作业管理器、Agent，以及 REST（health 版本、ai/foundation/simulation/data/agent 端点）。测试总数 43 → **62**。

### 不变 Unchanged
- 全部 85 个节点、所有原有 REST / WebSocket 端点、React Flow 编辑器、双语言 SDK、文档结构、6 篇深度文档、CI 流水线均保留可用。

## [0.5.3 Research Ready] — 2026

「科研就绪」升级：在不删除任何 v0.5.2 功能的前提下，补齐数据底座、统一运行时、报告与前端生态，使平台可端到端承载真实科研流程且**完全离线可运行**。**85 个科学节点 · 27 个分类 · 50 个模块 · 5 个官方 Demo · 43 项自动化测试**。

### 新增 Added

**统一运行时（外部程序缺失时诚实回退内置引擎，并在 `engine` 字段标注来源）**
- `ai_runtime/`：统一 LLM / 多模态推理运行时，`runtime.run(role, payload, backend=...)`、`describe()`、`register_builtin()`；支持 7 家供应商 + 离线回退。
- `database_runtime/`：统一数据库检索运行时，覆盖 Spectral / Chemical / Materials 三大类 17 个数据源，离线回退本地库。
- `simulation_runtime/`：四段式统一仿真运行时（`generate_input → run_tool → parse_output → to_object` + `internal_execute` 回退）：
  - 量子化学：ORCA / Gaussian / Psi4 / CP2K，回退**扩展休克尔（EHT）**引擎。
  - 分子动力学：GROMACS / LAMMPS / OpenMM，回退 **Lennard-Jones MD** 引擎（输出 RDF）。
  - 固体 DFT：VASP / Quantum ESPRESSO，回退**紧束缚 + XRD**引擎。
- `report_agent/`：汇总上游科学对象，一键生成 **Markdown / HTML / PDF** 报告，产物写入运行目录并记录路径。

**数据底座与节点生态**
- `data_layer/`：统一科学数据层，节点间传递对象而非裸文件。
- `node_registry/`：节点注册中心服务，导出 `registry.json`（作者 / 版本 / 模块 / 校验信息），供前端 **Node Marketplace** 浏览。
- 厂商适配器与质谱节点重构：GC-MS / LC-MS / MALDI-TOF / ICP-MS 等接入统一协议。
- 真实科研数据集：`datasets/`（咖啡因 EI-MS、分子库、显微镜 SEM 等）。
- Agent 节点系统：`Agent Planner` / `Scientific Agent`。

**前端**
- **Node Marketplace**：浏览 `registry.json`、按分类/标签搜索、拖拽添加节点（`GET /api/nodes/registry/full`）。
- 元数据驱动 UI：节点面板 / 检查器由注册信息自动渲染。

**Demo 工作流**
- `04_quantum_chemistry_profiling.json`：咖啡因 → 量子化学（EHT 回退）→ 分子描述符 → AI 性质预测 → Report Agent（HTML）。
- `05_multiscale_materials_simulation.json`：水分子 MD（LJ 回退）+ LiFePO₄ 固体 DFT（紧束缚回退）→ Report Agent（HTML）。

**部署**
- `docker/` 目录：`docker-compose.yml`（API 必选 + 可选的 db / proxy 配置档）、`nginx.conf`（反代 + `/ws` WebSocket 升级）、`.dockerignore`、`README.md`。

**性能**
- 几何嵌入力场（`models/geometry.py`）全量向量化，扩展休克尔单次回退从 ~74s 降至 ~0.4s（≈180×），结果不变。

### 变更 Changed
- 仿真节点改为 `simulation_runtime` 的轻量适配器，`backend_name` 决定外部程序，输出端口与 v0.5.2 完全一致。
- 根 `Dockerfile` / `docker-compose.yml` 升级至 `0.5.3`，并补齐新目录（`data_layer/ ai_runtime/ database_runtime/ simulation_runtime/ report_agent/ node_registry/`）。

### 不变 Unchanged
- 全部 77 个原有节点与所有 REST / WebSocket 端点、React Flow 编辑器、双语言 SDK、文档结构均保留可用。

## [0.5.2 Beta+] — 2025

首个公开 Beta+ 版本：**77 个科学节点 · 3 个官方 Demo · REST + WebSocket 后端 · React Flow 前端 · 双语言 SDK · Docker 一键部署 · 43 项自动化测试**。

### 新增 Added

**工作流引擎**
- `ScientificNode` 基类：`execute(inputs, ctx)` 契约、`get_param()`、`log()`、失败隔离（下游自动跳过）。
- `NodeRegistry` 注册表：`register` / `resolve` / `create` / `discover_package` / `discover_plugins`，支持 `@register_node` 装饰器与类型别名。
- DAG 执行器：NetworkX `topological_generations` 按代划分，同代节点 `ThreadPoolExecutor` 并行；支持菱形图。
- 端口类型系统：10 种科学数据类型，`Any` 通配，隐式转换 `ScientificReport/Molecule/Material → Text`。
- `ParameterSpec` 声明式参数：`string/text/integer/float/number/boolean/enum/path/file/molecule/material/list/dict`，`(value, label)` 下拉选项，`min/max` 范围校验。
- `EventBus` 事件总线 + `ResultCache` 结果缓存（SHA-1 缓存键：类型 + 参数 + 输入）。
- 工作流校验：节点 ID 唯一、类型已注册、无环、端口存在且类型兼容、必填端口已连接；`edges` 支持 `["a", "b"]` 简写。

**科学对象协议**
- `Spectrum`（含 `peaks`/`axis`/`technique`/`metadata`）、`Molecule`、`Material`（晶胞 + 位点 + 性质）、`Table`、`Image`、`SpectralMatch`、`Reaction`、`Text`、`ScientificReport`——全部基于 Pydantic v2，节点间传递的是对象而非裸文件。

**77 个科学节点（24 个分类）**
- `Questions`（2）：Unknown Compound Identification、Material Discovery。
- `Instruments`（26）：LC-MS / GC-MS / MALDI / ICP-MS、¹H 与 ¹³C NMR、IR、Raman、UV-Vis、Fluorescence、XPS、XAS、XRD、单晶 XRD、SEM、TEM、AFM、DSC、TGA、DMA、CV、EIS、DLS、BET、Raman Mapping、FTIR Imaging、Hyperspectral。
- `AI`（9）：LLM Reasoner（7 家供应商 + 离线回退）、ChemBERTa、GROVER、Graphormer、Uni-Mol、Vision Model（ViT/CLIP/SAM/DINO）、Train Model、Property Prediction、Similarity Search。
- `Databases`（14）：MassBank / MoNA / GNPS / HMDB / BMRB / NIST / PubChem / ChEMBL / ZINC / PDB / Materials Project / COD / ICSD / AFLOW。
- `Simulation`（7）：ORCA / Gaussian / Psi4 / CP2K / GROMACS / LAMMPS / OpenMM。
- `Analysis` / `IO` / `Report`（19）：基线校正、平滑、峰提取、归一化、重采样、谱运算、分子描述符、相似度、子结构检索、官能团；谱图文件（mzML/mzXML/MGF/MSP/JCAMP/XY/Bruker）、表格文件、分子/材料/文本输入、导出；报告构建、汇总表、报告导出（MD/HTML/JSON）。

**计算层**
- 依赖无关的 SMILES 解析器、Morgan/ECFP 指纹、分子描述符。
- 扩展休克尔（EHT）量子化学求解器。
- Lennard-Jones 分子动力学 + RDF。
- 谱学预测器：NMR 化学位移与 J 耦合、IR/Raman 官能团谱带库、UV-Vis Woodward-Fieser、EI-MS 碎裂规则。
- VF2 子结构同构、FAISS/NumPy 向量检索。
- 本地分子库（约 400 化合物）与材料库（18 种材料）。

**后端与前端**
- FastAPI 应用工厂 + lifespan 节点发现、CORS、`/api` 路由：节点目录、工作流 CRUD/校验/执行、运行历史与产物下载、WebSocket 实时事件流。
- React 18 + TypeScript + React Flow + Tailwind 三栏编辑器（节点面板 / 画布 / 检查器 + 控制台），中英文一键切换，节点拖拽、连线、参数编辑、实时运行日志。
- 产物持久化到 `output/<run_id>/artifacts/`。

**SDK**
- `chemml-sdk`（Python）：节点编写原语 + 零依赖 REST 客户端 + `run_local()` 进程内执行。
- `chemml-node-sdk`（Node.js）：`EventEmitter` 客户端 + WebSocket 事件流，5 项测试。

**Demo 工作流**
- `01_unknown_compound_identification.json`（10 节点）：咖啡因 EI-MS → 峰提取 → 平滑 → 多证据鉴定 → 库排序 → CSV + HTML 报告。
- `02_battery_material_discovery.json`（10 节点）：LiFePO₄ 晶胞 → XRD → 峰检索 → 材料发现排序 → 汇总表 → 决策报告。
- `03_catalyst_design.json`（11 节点）：乙酰氯 + 苯 → ORCA 单点能 → ChemBERTa 嵌入 → 相似性检索 → LLM 方案设计 → 催化剂导出。

**文档与工程化**
- `docs/` 五篇深度文档：`architecture.md`（四层架构、执行模型、事件与缓存、设计决策记录）、`node-development.md`（节点契约、端口、参数、调试、自检清单）、`workflow-format.md`（JSON 规范与端口兼容）、`api-reference.md`（REST/WS 逐端点参考）、`deployment.md`（三种部署形态、环境变量、生产检查清单）。
- `examples/plugins/melting_point_note.py`：可直接运行的自定义节点示例，配套 `examples/README.md`。
- `plugins/` 目录 + `.gitkeep`，作为 `CHEMML_PLUGINS` 默认发现位置。
- `LICENSE`（Apache-2.0 全文）、`CONTRIBUTING.md`（含节点提交自检清单）、`CHANGELOG.md`。
- `.gitignore` 与 `.github/workflows/ci.yml`：CI 覆盖 pytest、全节点冒烟、Demo 工作流、Node SDK、前端构建、Docker 镜像冒烟。
- `scripts/package.py`：一键打出整洁的分发 zip（排除 `node_modules`、缓存、运行时 `output/`）。
- Python SDK 新增 `Port` / `DATA_TYPES` 导出，以及 `save_workflow()`、`runs()`、`run_events()`、`run_detail()`、`artifact_url()` 与 `nodes(query=...)`；补齐 `node_sdk/python/README.md`。

**工程化**
- `Dockerfile`（多阶段、非 root 用户、HEALTHCHECK、单容器托管 API + 前端）与 `docker-compose.yml`（含可选的 postgres/redis profile）。
- `scripts/smoke_nodes.py`：77 个节点逐一实例化并执行，支持 `--filter/--list/--json/--traceback`。
- `scripts/run_demo_workflows.py`：校验并执行全部 Demo，支持 `--events`。
- 43 项 pytest 测试（引擎 / 节点 / 工作流 / REST API）。

### 修复 Fixed

- `parse_formula` 缺少 `position = match.end()` 导致节点加载时无限循环。
- 化学式正则数字组改为可选（`(\d+(?:\.\d+)?)?`），修复 `O`/`N`/`C8H9NO2` 等全部化学式解析失败。
- `ParameterSpec.coerce` 的 enum 分支无法匹配 `(value, label)` 元组选项，导致所有枚举参数静默回退到第一项。
- `Workflow.validate` 向 `connected` 集合插入 `Port` 对象而非端口名，导致必填输入检查永远失败。
- `LennardJonesMD.__init__` 未初始化 `self.time`。
- `compute_forces` 中 `0 * inf = nan` 运行警告（距离掩码安全化）。
- `TableFileNode` 改用 `utf-8-sig` 读取，修复 UTF-8 BOM 污染首列列名。
- `XRDNode` 用 `material.name` 解析晶胞位点导致含空格/括号的名称失败，改为从 `formula` 构建。
- 两个并发 `ReportBuilderNode` 写同名产物导致权限错误，改为按 `report_id` 命名。
- `PDBNode.parse_response` 引用局部变量 `query` 导致 `NameError`。
- `MPNNConfig` 参数字段名 `hidden_dim` → `hidden`。
- `build_material()` 增加 `source` 参数；`_helpers.write_artifact` 增加缺失的 `ROOT` 定义。
- 运行接口返回的 `artifacts` 为绝对路径，与 `GET /api/runs/artifacts/{path}` 要求的仓库相对路径不一致，导致产物下载不可用；改为返回相对路径。
- `backend/app.py` 从未挂载 `static/`，Docker 单容器部署只能拿到 API 而拿不到前端；补上 `StaticFiles` 挂载（置于 `/api/*` 路由之后，API 优先）。
- `Dockerfile` 的 `CMD` 忽略 `CHEMML_HOST` / `CHEMML_PORT` / `CHEMML_WORKERS`；改为读取环境变量。同时预设 `PYTHONPATH`，使容器内 `import chemml_sdk` 可用（插件依赖）。
- `nodes/loader.py` CLI 的端口数列读取了不存在的 `input_ports`/`output_ports` 键，恒显示 0；改为 `inputs`/`outputs`。
- Node SDK 的 `npm test` 使用 `node --test test/`，在部分平台（Windows/Git Bash）路径解析失败；改为 `node --test` 自动发现。
- Python SDK 未导出 `Port`，文档中的插件示例 `from chemml_sdk import ... Port ...` 会 `ImportError`；补齐导出并补充 `save_workflow`/`runs`/`run_events`/`run_detail`/`artifact_url` 方法。

### 变更 Changed

- 前端 `package.json` 显式声明 `@esbuild/win32-x64` 与 `@rollup/rollup-win32-x64-msvc` 平台二进制，修复 Windows 下构建失败。

## [未发布]

- `docs/` 深度文档持续扩充。
- `examples/` 插件示例扩充。
