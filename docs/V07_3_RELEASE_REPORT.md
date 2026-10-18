# Chem ML Platform v0.7.3 — 发布报告（V07_3_RELEASE_REPORT）

- **版本**：`0.7.3`
- **发布提交**：本报告**不写死提交哈希**——它无法记录包含自身的那个提交。请以
  `git describe --tags` 与 `docs/RELEASE_MANIFEST.json` 的 `commit` 字段为准。
- **执行环境**：Windows 11（win32 · AMD64）· Python 3.13.12（隔离 venv `chemml`）·
  Node.js 22.12.0 · 宿主机 Python 3.13.6（**无 torch**，桌面版实际使用）
- **配套材料**：`CHANGELOG.md`（含「外部审计响应」小节）、`docs/PROVENANCE.md`、
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

v0.7.3 交付三项新能力（硬碳预脱溶剂机理可视化、二维声学全波形反演、API Key 入口与
Agent 工具守卫），并在**一轮独立审计之后**关闭了全部 4 项 P0 与 4 项可在本版完成的 P1。
其中最关键的一项是**发布打包器此前会把明文 API Key 与桌面会话令牌打进公开归档**——
规则读起来像白名单，实际是一条否定规则；本次归档里那个文件恰好是空的 `{}`，
**不是因为规则安全，而是因为打包时那台机器还没配过 Key**。

**仍未完成**：干净虚拟机安装验证、安装包代码签名、Linux/macOS 实机验证、真实数据集的
科研验证。因此 v0.7.3 的定位是 **Alpha / Research Preview**。

---

## 1. 本版审计响应摘要

审计对 `Chem-ML-Platform-v0.7.3.zip` 提出了 4 项 P0 与 7 项 P1。逐条对应如下，
每项都有回归测试；详细论证见 `CHANGELOG.md` 的「修复 Fixed — 外部审计响应」。

| 编号 | 审计指出的问题 | 处置 | 回归测试 |
| --- | --- | --- | --- |
| **P0-1** | `package.py` 用 `endswith("ai.json")` 冒充白名单，`config/credentials.json`、`config/session.json`、`.env*`、`plugins/` 会进公开归档 | 改为**正向白名单** `CONFIG_ALLOWLIST`；补 `.env*` / 私钥 / 顶层 `plugins/` 排除；**打包后重扫归档**，命中即删除并非零退出 | `tests/test_v07_3_packaging_secrets.py`（41 项，含种入哨兵密钥的端到端打包与真实仓库树扫描） |
| **P0-2** | 全量测试与 FWI 验收在审计容器内超时 | 本机**实际跑完**：689/689 测试通过 · `check_fwi.py` `all checks passed` · 门禁 PASSED（见 §2）。报告只记录真实退出码，**超时从未被计入 PASS** | 全量 pytest + `tests/check_fwi.py` |
| **P0-3** | `tool_guard.py` 文档声称「所有入口共用一个判定点」，但引擎从不调用它 | 守卫接入 `WorkflowEngine._tool_guard_refusal`，三入口共用同一决定；`deny` 绝对拒绝，`approval` 按 origin 区分；守卫缺失时**如实声明降级** | `tests/test_v07_3_engine_tool_guard.py`（13 项） |
| **P0-4** | 注册表把 99/99 节点统一登记为 `internal_approximation`，与 `requires_network` / `requires_external_software` 自相矛盾 | 注册表拆出 `supported_execution_modes`（由能力推导）与 `default_execution_mode`；**实际**执行模式、`engine_name`、`fallback_reason` 记入 provenance | `tests/test_v07_3_execution_modes.py`（11 项） |
| **P1-1** | 连通性探测对所有服务商硬编码 `gpt-4o-mini`，把有效 Key 报成无效；且不读 `base_url` 覆盖 | 每 provider 独立的 `probe_model` / `probe_path` / `probe_style`；Anthropic 走原生 Messages API；本地 provider 探测服务地址；新增 `outcome` 分类并在界面按**失败原因**着色 | `tests/test_v07_3_credential_probe.py`（23 项，真实本地 HTTP 服务） |
| **P1-2** | 明文文件回退在 Windows 上仅靠 `chmod(0o600)` | 文档化为已知限制；**打包器绝不携带该文件**（P0-1 的核心收益） | 同 P0-1 |
| **P1-3** | `docs/PROVENANCE.md` 标题仍为 v0.7.2；CHANGELOG 测试数量与实际不符（31/21/22 vs 36/25/24） | 已更新；**测试数量按实际函数数改正**；`version.py --check` 新增覆盖发布文档（并验证它真能报出漂移） | `tests/test_v07_2_version_consistency.py` |
| **P1-4** | `test_the_credential_file_is_gitignored` 只调 `git check-ignore`，源码归档无 `.git` 必然失败 | 改为断言 `.gitignore` **规则本身**并实现完整 gitignore 语义；Git 降为第二意见 | `tests/test_v07_3_credentials.py` |
| **P1-6** | `SeismicForwardNode` 四个输出全部悬空；`truth` 端口在端口层面是必需的，真实数据无法运行 | `forward.energy` 接入 `submit.forward_qc`（CFL 裕度 / 各炮能量 / 死炮计数进入 `run_summary.json`）；`truth` 与 `forward_qc` 标记 `optional` | `tests/test_v07_3_seismic_fwi.py`（24 项） |

### 未在本版闭环的审计事项（明确列出，不计入 PASS）

| 事项 | 原因 | 归属 |
| --- | --- | --- |
| P1-5 数据集逐条许可核实 | 自动扫描**无法判断数据集授权**，须人工逐条确认 | `docs/PROVENANCE.md` §2.5 OSS-003 |
| P1-5 Octop 来源记录 | 已补：§2.5 明确记为**仅概念借鉴，无代码派生** | 已完成 |
| P1-7 独立验证（独立正演器 / 真实数据） | 需要平台之外的算力与授权数据 | v0.8 路线 |
| 干净环境安装、代码签名 | 需目标虚拟机与证书 | 未执行 |

---

## 2. 实测结果

下表**只记录实际运行的命令**。审计容器内超时的项目在本机重跑并给出真实退出码。

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `python -m pytest tests/ -q` | **781/781 通过**，见 §2.1 | 全量套件 |
| `tests/check_fwi.py` | **`all checks passed`**，见 §2.2 | FWI 合成验收 |
| `python scripts/quality_gate.py` | **PASSED**，见 §2.3 | 质量门禁 |
| `python scripts/version.py --check` | `OK: every artefact agrees on 0.7.3` | 已扩展覆盖发布文档 |
| `python scripts/license_report.py --check` | `[PASS]`，见 §2.4 | 第三方许可证 |
| `python scripts/dataset_governance.py --check` | `OK: 10 dataset metadata records are consistent` | 数据集治理 |
| `python -m node_registry --write` + `scripts/node_catalog.py --check` | `99 nodes / 30 categories` · `OK` | 注册表与 README 同步 |
| `python scripts/package.py` | `scan : clean`，见 §2.5 | 归档后密钥扫描 |
| 前端 `npm run build`（tsc + vite） | `tsc clean` · 3 files，见 §2.5 | 生产构建 |
| `desktop` 构建（NSIS） | `Setup 0.7.3.exe`，见 §2.5 | 安装包 |
| `scripts/refresh_desktop_payload.py --verify --all-installed` | 3/3 `AGREES`，见 §2.5 | 桌面载荷一致性 |
| 工作流 09 在**用户实际启动的那一份**、**无 torch** 宿主机实跑 | `completed` · 0 失败，见 §2.6 | 桌面版真实依赖 |
| **NVIDIA NIM 探测 + 端到端推理（真实 Key）** | `ok` · HTTP 200 · 1.7 s；`engine=remote` · 5.8 s，见 §2.7 | 第三方 Key 入口 |
| **工作流 10 公众号营销文（联网实跑）** | `completed` · 26.5 s · 0 失败，见 §2.8 | 内容创作工作流 |

### 2.1 全量测试

`python -m pytest tests/ -q` → **781 项执行，全部通过，零失败零错误**。分类普查（call phase）：

| 分类 | 通过 |
| --- | --- |
| unit | 396 |
| integration | 187 |
| security | 135 |
| benchmark | 18 |
| desktop | 45 |
| **合计** | **781** |

门禁另以独立阶段跑 `host_dependent_tests`（7/7 通过），门禁自报的收集数含该阶段——
两个数字口径不同：781 是单次 `pytest tests/` 的执行数，门禁自报的是各阶段 marker
合并后的收集数。

新增 7 个测试文件：

| 文件 | 项数 | 锁住的问题 |
| --- | --- | --- |
| `test_v07_3_packaging_secrets.py` | 41 | 归档不得携带凭据 / `.env*` / 私有插件 |
| `test_v07_3_credential_probe.py` | 23 | 每家服务商的探测形态与失败分类 |
| `test_v07_3_engine_tool_guard.py` | 13 | 守卫在 GUI / REST / CLI 三条入口上都生效 |
| `test_v07_3_execution_modes.py` | 11 | 声明模式 vs 实际模式分离 |
| `test_v07_3_unbound_names.py` | 60 | 节点模块不得使用未 import 的类名 |
| `test_v07_3_nvidia_provider.py` | 16 | 410 / 503 与「Key 无效」必须区分 |
| `test_v07_3_wechat_workflow.py` | 10 | 工作流 10 的结构与离线降级 |

另新增 `test_v07_3_llm_context.py` 6 项（上游文本不得被截断），并扩充地震 FWI 测试
（19 → 24 项）与凭据 gitignore 测试。

### 2.2 FWI 验收

`python tests/check_fwi.py` → **`all checks passed`**，四组全部 PASS：

| 组 | 关键回显 |
| --- | --- |
| 1. 子波与几何 | 子波主峰落在窗口内（peak@16 / 187），非边界伪影 |
| 2. 正演一致性 | 炮集完整，**held-out 炮 [1, 6] 未参与梯度**（used=[0,2,3,4,5,7]） |
| 3. 伴随梯度方向 | `max|g| = 3.754e+07` 有限；大块解析/数值同号（+1.6813e+08 / +1.3211e-03）；沿梯度下降 **+4.79%**，沿上升 `1.0401 → 1.0566` |
| 4. 反演 | 三阶段均实际前进：6.1764e-12→4.5542e-12（−26.27%）、7.5380e-12→6.4094e-12（−14.97%）、5.8286e-12→4.8362e-12（−17.03%）；整体 **8.9068e-12 → 4.8362e-12（−45.70%）**，12 次迭代 30.1 s |
| 4. 泛化 | **held-out 炮误差 2.0829e-12 → 1.9542e-12**（未参与梯度的炮也下降） |
| 4. 结构恢复 | 横向相关系数 **0.1247**；速度范围 [1500, 2321] m/s；子波已估计 |

> §2.2 与 §2.6 的数字**不同，这是预期的**：§2.2 是隔离 venv（`chemml`，有 torch）里
> `check_fwi.py` 的验收结果；§2.6 是**无 torch 宿主机**上跑真实工作流的产物。
> 两者是不同机器、不同依赖面下的独立运行，只有「误差下降且 held-out 炮同样下降」
> 这一**定性结论**应当一致，具体数值不要求相同。

### 2.3 质量门禁

`python scripts/quality_gate.py` → 27 阶段，最终 **PASSED：pass=26 · fail=0 · skip=1 · timeout=0 · error=0**
（门禁自报 `tests collected across stages: 696`）。

首轮实测为 pass=24 · fail=1 · error=1，两处失败均已定位并修复：

| 阶段 | 首轮 | 最终 | 处置 |
| --- | --- | --- | --- |
| `release_manifest` | FAIL | **PASS** | 清单记录 `0.7.3@ffa8585`，工作树已到 `0.7.3@ab803b7`。**预期行为**：清单记录的是上一次提交，必须在本轮源码提交后重新生成（见项目发布顺序：安装包 → 归档 → 清单 → 门禁）。修复后 `OK: manifest matches 0.7.3@ab803b7 (21/21 built)` |
| `credential_scan` | ERROR | **PASS** | **本轮引入的真 bug**：给该阶段加豁免集时把 `patterns`（`re.Pattern` 列表）当成 `(pattern, label)` 元组用，`matched.group(...)` 抛 `AttributeError`。改为直接取 `p.search(text)` 的 match 对象 |

最终 PASS 的 26 个阶段中与本轮相关者：`python_compile` 248 个一方文件 ·
`unit_tests` 396/396 · `integration_tests` 187/187 · `security_tests` 135/135 ·
`benchmark_tests` 18/18 · `desktop_tests` 45/45 · `host_dependent_tests` 7/7 ·
`workflow_json_validation` 10 个工作流合法 · `demo_workflows_dry_run` **10/10**
（本轮新增的工作流 10 已被门禁自动发现并跑通）·
`reproducibility_verification` 2 工作流 × 2 次 ·
`frontend_typescript` `tsc clean` · `frontend_production_build` ·
`electron_installer_artefact`（75.5 MiB）· `version_consistency` ·
`release_manifest`（`OK: manifest matches 0.7.3@5257df2`）·
`dependency_licenses` · `license_sbom_report` · `credential_scan` · `release_cleanliness`。

唯一 SKIP 为 `host_gpu_status`：`torch 2.14.1+cpu present, CUDA not available on this host`
——本机无 GPU，属环境事实而非跳过未做。

`credential_scan` 的回显包含豁免明细，因此豁免不是静默的：
`no hardcoded credentials in shipped sources (3 fake keys in redaction fixtures, excluded by design) (2 scanners exempt by exact filename: …)`。
实测 3 个扫描器中 `scripts/package.py` 与 `scripts/quality_gate.py` 因含私钥块字面量而命中自己；
`scripts/license_report.py` 当前未命中（它用自己的 `_SECRET_ALLOW_FILES`），保留在豁免集中是
**防御性冗余**——规则集一旦改动就会命中自己。

> 门禁过程中真实发现并修掉的一处**自我阻断**：给 `scripts/quality_gate.py` 加私钥块正则后，
> 归档扫描器在它自身命中该形状并**拒绝发布**（`REFUSING TO PUBLISH … 1 secret/leak finding(s)`），
> 3 项归档测试因此失败。扫描器必须写出它要找的形状，于是每个扫描器都会命中自己——
> 豁免集改为**逐文件精确列举**（目录级豁免会放过同目录的真实密钥），并加测试锁定
> 「每个扫描器都同时出现在打包器与门禁的豁免集里」「豁免项不得互为目录前缀」，
> 以及一条**扫描真实仓库树**的测试（合成夹具无法发现这类问题）。

### 2.4 许可证与数据集治理

| 检查 | 结果 |
| --- | --- |
| `scripts/license_report.py --check` | `[PASS] licence/SBOM report (12 py / 153 npm / 9 external)`；0 个强copyleft 许可被分发 |
| `scripts/dataset_governance.py --check` | `OK: 10 dataset metadata records are consistent` |
| `scripts/node_catalog.py --check` | `OK: README / stats agree with the node registry` |

注：`faiss-cpu` 为声明的可选组件，未安装 → 能力降级，**不计入 FAIL**。

### 2.5 前端与桌面

| 检查 | 结果 |
| --- | --- |
| `npm run build`（`tsc -b && vite build`） | `tsc clean` · `dist built with 3 files` |
| `scripts/version.py --check` | `OK: every artefact agrees on 0.7.3` |
| 安装包 | `Chem ML Platform Setup 0.7.3.exe` · 79 147 833 B（75.5 MiB）· 重新构建于本次提交之后 |
| `scripts/refresh_desktop_payload.py --verify --all-installed` | 修复前 **2 of 3 STALE** → 刷新后 **3 of 3 AGREES** |

`ApiKeyPanel.tsx` 的改动（探测结果按**失败原因**着色：成功 / 可恢复 / 失败三档，
并显示实际探测的 `base_url`）已通过 `tsc` 类型检查与生产构建。

**载荷刷新不是形式检查**：`--verify --all-installed` 在刷新前明确报出用户实际启动的
那一份（`C:\Users\hanku\Desktop\0.5\Chem ML Platform\resources\app`）有
**14 个文件与源码不一致 + 1 个缺失 + 构建印章指向旧提交**——本轮 11 处改动在那份副本里
全部没有生效。这正是 v0.7.2 交付「改了但没生效」的同一个坑。刷新后该副本
`updated 16/236, removed 1`，并保留了 33 项运行期产物（`output/` / `memory/` / `config/`
属用户数据，不作为构建产物清除）。

### 2.6 无 torch 宿主实跑（**在用户实际启动的那一份上**）

宿主解释器 `D:/python 3.13.6/python.exe`（已确认 `torch present: False`，即桌面版实际
使用的依赖面），工作目录为 `C:\Users\hanku\Desktop\0.5\Chem ML Platform\resources\app`
——**不是仓库副本**。实跑工作流 09「二维声学全波形反演（赛题）」：

| 项 | 实测值 |
| --- | --- |
| 状态 | `completed`，4 节点，**0 失败** |
| `forward_qc.connected` | `True` · 8 炮 · `dead_shots = 0` |
| CFL | `cfl_dt_limit_s = 2.7159e-03` · `requested_dt_s = 1.5e-03` · `cfl_margin = 1.8106` · `cfl_admissible = True` |
| 各炮能量 | min 1.4660e-12 · median 6.0740e-12 · max 8.9036e-12 |
| 误差 | 8.905595e-12 → **5.109689e-12**（−42.62%），12 次迭代 |
| held-out 炮 | `[1, 6]` 未参与梯度；误差 2.083164e-12 → **1.997502e-12**（`held_out_improved = True`） |

`forward_qc` 的存在本身就是 P1-6 的验收证据：正演节点的输出**第一次被真正消费**，
且 `cfl_margin = 1.81` 证明反演是在一个数值上可接受的起始模型上开始的——此前
「误差下降」缺少可比对的基线。这条比任何单元测试都更能说明交付有效，因为它跑在
用户双击打开的那一份上，且该机器**没有 torch**。

### 2.7 第三方 API Key 入口：NVIDIA NIM（真实 Key 实测）

凭据入口新增 `nvidia`（`NVIDIA_API_KEY` → `https://integrate.api.nvidia.com/v1`），
凭据目录与 LLM 节点目录**两张表同步新增**。以下全部为对一把真实 Key 的实测结果，
**不是文档摘抄**——平台实际行为与公开文档多处不符。

| 检查 | 实测结果 |
| --- | --- |
| `GET /v1/models` | HTTP 200 · 0.53 s · 返回 **81** 个 id |
| 连通性探测 `test_credential("nvidia")` | `ok` · HTTP 200 · **1.7 s** |
| 凭据存储后端 | **系统密钥环**（`WinVaultKeyring`），非明文文件 |
| `LLMNode` 端到端推理 | `engine=remote` · **5.8 s** · 中文营销文案正常返回 |

**平台行为与文档不符的三处（均已按实测写死）：**

1. **模型目录 ≠ 可用清单。** 目录里的多数 id 调用即 **HTTP 410**（end of life）或
   404，例如 `meta/llama-3.1-8b-instruct` 返回 `410 Gone: reached its end of life on
   2026-08-26`。因此 410 被单独分类为 `model_unsupported`（换模型），**绝不并入
   `invalid_key`**——后者会让用户去重生成一把本来可用的 Key。
2. **用户指定的 `deepseek-ai/deepseek-v4.1-flash` 当前无响应。** 它在目录中、接受
   连接，但**连续 300 秒零字节**；同一把 Key 下 `openai/gpt-oss-20b`（1.0 s）与
   `stepfun-ai/step-5-preview`（1.7 s）返回 200。判定为该模型后端不可用，**不是**
   Key 或网络问题（Key 已由同端点其他模型证明有效）。探测模型因此取实测可用的
   `openai/gpt-oss-20b`；用户指定的模型名仍可手动填入。
3. **免费额度主力模型是推理模型。** token 预算不足时返回 `content: null` +
   `finish_reason: length`：实测 `max_tokens=400` 正文为空，`max_tokens=3000` 才出稿
   （`finish_reason: stop`）。原先的解析会把 `null` 读成字符串 `"None"`——一个非空
   但毫无内容的回答，看起来像模型答过了。

**由此发现并修复的三处既有缺陷**（详见 CHANGELOG）：

- `ExportNode` 的 Markdown 分支用了未 import 的 `ScientificReport`，**导出报告为
  Markdown 必然崩溃**；此前从未暴露，因为已发布工作流导出的都是 JSON/CSV。
- `LLMNode._render_context` 用 `Text.summary()`（**120 字符预览**）转发上游文本，
  742 字策划只剩前 120 字传给下游，下游模型在信息缺失下**自信地写了一篇关于
  「智慧烹饪机」的营销文**——不报错、不告警、输出看着完全合理。展示用截断不能
  出现在数据路径上。
- `_stored_secrets` 从不查系统密钥环（有 Key 环的机器上，刚保存的 Key 探测永远
  返回「未配置凭据」）；`LLMNode` 也从不读用户配置的 `base_url` 覆盖。

### 2.8 公众号营销文工作流（联网实跑）

`workflows/10_wechat_marketing_copy.json`：卖点输入 → **选题策划** → **正文撰写**
→ 汇总 → 导出 Markdown。两个 LLM 节点分工，策划的输出是撰写的显式上游输入。

| 运行方式 | 结果 |
| --- | --- |
| **联网实跑**（仓库，NVIDIA `openai/gpt-oss-20b`） | `completed` · **26.5 s** · 0 失败节点 · Markdown 产物已生成 |
| **联网实跑**（**用户实际启动的那一份**，无 torch 宿主机） | `completed` · **36.8 s** · `engine=remote` · 密钥环读取成功 |
| **离线降级**（无 Key） | `completed` · 两个 LLM 节点 `engine=offline` · 结构完整 |

第二行是最有说服力的一条：它跑在 `C:\Users\hanku\Desktop\0.5\Chem ML Platform\
resources\app`——用户双击打开的那份，不开浏览器、不带 torch，且 Key 是从**系统密钥环**
读出来的（不依赖任何环境变量或明文文件）。这同时验证了 §2.7 里「密钥环凭据读不出来」
那处修复在真实部署形态下确实生效。

联网运行的成稿确实承接了策划：策划给出标题「实验室安全新标杆：380 g 智能安全帽」，
正文首节即为「轻量化设计：380 g 的佩戴体验」，四节结构与结尾行动号召齐备。

> 第一次实跑时**正文完全跑题**（写成了「智慧烹饪机」）。根因不是模型，是上游策划
> 被 `Text.summary()` 截断成 120 字符——见 §2.7。这类缺陷没有任何工具会主动报告：
> 不抛异常、不产生告警，输出是一篇语法完整、格式正确、只是答非所问的文章。

---

## 3. 节点状态（注册表实测，非声明）

| 项 | 数量 |
| --- | --- |
| 节点总数 / 分类数 | 99 / 30 |
| `capability_status = verified` | **4** |
| `capability_status = executable` | 86 |
| `capability_status = experimental` | 1 |
| `availability = unavailable`（本机缺外部依赖） | 8 |
| 支持 `internal_approximation` **且** `external` 两种模式 | **24**（此前注册表对这 24 个节点只承认前者） |
| 携带 `validation_evidence` | 5 |

**这 4 个 `verified` 是本项目的诚实上限。** 其余 95 个节点虽可运行，但尚无独立验证证据，
不应被表述为已验证。审计对此的判断（本报告采纳）：节点覆盖面广 ≠ 科研有效性已建立。

---

## 4. 科研有效性边界（必须与「功能可用」分开读）

| 能力 | 实际是什么 | **不是什么** |
| --- | --- | --- |
| 硬碳预脱溶剂 | 以论文 4 个实测锚点校准的**解析代理模型** | 不是 VASP / NEB 复现，不是 COMPASS MD，不是 XPS 实验 |
| 二维声学 FWI | 平台自建的**二维常密度声学有限差分**求解器 + 伴随梯度 | 不是工业地震成像软件；当前基准由**同一个正演模型**生成数据，存在 inverse crime 风险 |
| LC-MS/MS 基准 | 合成 / 手工参考数据上的**回归门槛** | 不是真实样本鉴定准确率，不能外推 |
| 内部编码器（ChemBERTa / GROVER / Graphormer / Uni-Mol 命名） | **内部近似实现，无原始预训练权重** | 不是原论文模型；命名保留以对应论文，不构成对原模型权利的主张 |

审计提出的两条方法学建议，本版已部分采纳：
**FWI 的正演节点输出现已进入 `run_summary.json` 的 `forward_qc`**，给出反演前起始模型的
CFL 裕度与各炮能量，使「误差下降」有了可对照的基线；`truth` 端口改为可选后，
**真实数据路径在端口层面可用**（评分字段显式为 `null`，不伪造）。

---

## 5. 已知限制

1. **发布打包器已修复，但明文凭据回退本身仍在**（P1-2）。无 OS 密钥环时密钥写入
   `config/credentials.json`；界面已如实告知。本版保证的是**该文件绝不进入公开归档**。
2. **守卫在 Agent 路径上更严，在手动路径上更松**，这是有意为之：本地用户点 Run 就是批准，
   对每个报告导出再弹一次确认，只会训练用户闭眼点掉。
3. **FWI 基准的 inverse crime 未解决**：正演与反演共享模型假设，会高估表现。需要独立正演器。
4. **Electron GUI 无法在本执行环境验证**（无桌面会话，Electron 会 `exitcode=0` 静默退出）。
   已用对照实验确认与代码无关，但**只能由用户在真实桌面上确认 API Key 面板交互**。

---

## 6. 发布门禁自检

- [x] 打包测试证明凭据、会话、`.env`、用户插件不会进入公开 ZIP（哨兵端到端测试）
- [x] 全量套件在本机完成，超时项单独列出，不计 PASS
- [x] 节点能力目录的执行模式字段准确，运行记录带 `engine` / `fallback_reason`
- [x] 版本报告、CHANGELOG、PROVENANCE、SBOM、依赖锁与源码归档版本一致
- [x] API Key 连接测试覆盖每家服务商、错误模型、`base_url` 覆盖、网络失败与密钥脱敏
- [x] FWI 合成基准通过，并明确其与真实地震数据验证的区别
- [ ] **至少一个有来源与授权证明的真实科研数据集完成端到端评估** —— **NOT PERFORMED**
- [ ] **独立安装器在干净环境完成安装 / 升级 / 卸载验证** —— **NOT PERFORMED**
- [x] 开源来源清单已处理 Octop 设计来源记录（§2.5）

---

## 7. 复现步骤

```bash
python -m pytest tests/ -q
python scripts/quality_gate.py
python tests/check_fwi.py
python scripts/version.py --check
python scripts/license_report.py --check
python scripts/dataset_governance.py --check
python -m node_registry --write && python scripts/node_catalog.py --check
python scripts/package.py --name Chem-ML-Platform-v0.7.3 --output ../Chem-ML-Platform-v0.7.3.zip
```
