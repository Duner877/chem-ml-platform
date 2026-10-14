# v0.7.2 问题记录表（Issue Log）

> 任务书 §三 要求：**每个 Issue 必须包含**「问题描述、复现步骤、预期行为、实际行为、修改范围、
> 自动化测试、验收证据和关联提交」八项。本表逐条给出，不省略、不合并、不美化。
>
> 关联提交：`2eb6453`（v0.7.2 首个提交）及其后的 v0.7.2 收尾提交；标签 `v0.7.2`。
> 表中「本次」指按 v0.7.2 任务书实施期间发现并修复的问题，其中多数是**在补齐 P0/P1 证据时
> 才暴露出来的**——这正是任务书要求「先建立可复现测试，再宣称可信」的原因。

---

## 索引

| ID | 任务 | 严重度 | 一句话 |
|---|---|---|---|
| ISSUE-01 | P0-01 | 高 | 只读令牌可触发内联工作流执行 |
| ISSUE-02 | P0-01 | 高 | 运行级接口无归属校验 |
| ISSUE-03 | P0-01 | 中 | 越权返回 401，无法与「未认证」区分 |
| ISSUE-04 | P1-06 | 高 | `output_digests` / `output_artifacts` 声明但从未填充 |
| ISSUE-05 | P1-06 | 高 | 复现摘要混入运行期身份，重复运行必然「不一致」 |
| ISSUE-06 | P1-06 | 中 | 无自动化手段验证「声明的确定性」 |
| ISSUE-07 | P1-03 | 中 | 超时终止无自动化测试（验收缺口） |
| ISSUE-08 | P0-05 | 中 | `DependencyMissingError` 构造签名不匹配 |
| ISSUE-09 | P0-04 | 低 | `git_commit()` 恒返回 `unknown` |
| ISSUE-10 | P0-02 | 中 | 运行时探针把 Python 3.13.14 判为超出支持范围 |
| ISSUE-11 | P0-02 | 中 | `spawnSync` 在受限主机上 `EBUSY` 并阻塞主进程 |
| ISSUE-12 | P0-03 | 高 | CI 流水线因 `sys.modules` 未注册而无法启动 |
| ISSUE-13 | P0-03 | 中 | 质量门漏 `import shutil`，探针阶段 `NameError` |
| ISSUE-14 | P0-03 | 高 | 探针阶段「未读到结论却报告 PASS」 |
| ISSUE-15 | P0-03 | 中 | `--basetemp` 剥离逻辑错误致 6 个阶段 `ValueError` |
| ISSUE-16 | P1-08 | 中 | `requirements.txt` 的 `-r` 行被当作包名解析 |
| ISSUE-17 | P0-04 | 高 | 许可清单随本机构建产物变化，发布清单必然漂移 |
| ISSUE-18 | P0-04 | 高 | 版本一致性检查覆盖不全：启动横幅 v0.6.0、网页标题 v0.7.1、86 个节点 0.7.1 |
| ISSUE-19 | 发布干净性 | 低 | 测试残留 `workspace/raw_data/x.csv` 随源码包发布 |
| ISSUE-20 | P0-02 | 中 | 桌面壳前端回退路径与打包产物位置不一致（回退永不生效） |
| ISSUE-21 | P1-06 | 低 | 解压出的副本无法自报来源提交（`git_commit()` 恒为 `unknown`） |
| ISSUE-22 | P0-01/P1-02 | 中 | API 与文档声称「启动脚本注入会话令牌」，实际仅桌面壳注入 |
| ISSUE-23 | P0-03 | 低 | 版本检查在 `CHANGELOG.md` 缺失时抛异常而非报告漂移 |
| ISSUE-24 | P1-06 | 中 | 祖先 Git 仓库的 HEAD 被当作本树的构建提交（溯源造假） |
| ISSUE-25 | P0-04 | 中 | 载荷刷新与构建印章互相覆盖，每轮恒定 2 个伪更新、永不收敛 |
| ISSUE-26 | P0-03 | 中 | 门禁编译阶段把测试夹具计为「一级源码文件」，数字逐轮虚增 |

---

## ISSUE-01 — 只读令牌可触发内联工作流执行

- **问题描述**：`POST /api/workflows/run`（内联运行）在 v0.7.1 中被归类为 `read` 权限。该路由不匹配
  `.+` 形式的既有规则（旧规则只覆盖 `/api/workflows/<name>/run`），因此只读令牌可以发起完整工作流执行。
- **复现步骤**：设置 `CHEMML_SESSION_TOKEN` 与 `CHEMML_READONLY_TOKEN`，以只读令牌 `POST /api/workflows/run`
  并携带 `{"nodes": [], "edges": []}`。
- **预期行为**：返回 403（已认证但权限不足），拒绝执行。
- **实际行为**：v0.7.1 返回 200，工作流被执行。
- **修改范围**：`backend/security.py`（新增显式 execute 路由规则）。
- **自动化测试**：`tests/test_v07_2_ws_security.py::TestHttpParity::test_readonly_token_may_not_execute`。
- **验收证据**：安全套件 133 项全通过；`output/gate_logs/security_tests.log`。
- **关联提交**：`2eb6453`。

## ISSUE-02 — 运行级接口无归属校验

- **问题描述**：`GET /api/runs/{run_id}/events` 与 `GET /api/runs/{run_id}` 在 v0.7.1 中没有任何
  运行级授权检查。任何持有合法令牌的人都能订阅他人的运行事件。若不修复，新增的 WebSocket 运行级
  检查只是装饰——同一份数据仍可经 HTTP 取走。
- **复现步骤**：以只读令牌请求一个由其他 principal 创建的 `run_id` 的事件流。
- **预期行为**：403（非归属者），且未知 `run_id` 返回与越权一致的状态，不泄露运行是否存在。
- **实际行为**：v0.7.1 直接返回事件数据。
- **修改范围**：`backend/run_registry.py`（新增）、`backend/routers/workflows.py`、`backend/security.py`。
- **自动化测试**：`tests/test_v07_2_ws_security.py::TestHttpParity::test_run_events_endpoint_enforces_ownership`、
  `::test_run_status_hides_foreign_runs`；WebSocket 侧 `backend/ws_auth.py` 同源判定。
- **验收证据**：安全套件全通过；WebSocket 关闭码 `4403`。
- **关联提交**：`2eb6453`。

## ISSUE-03 — 越权返回 401，无法与「未认证」区分

- **问题描述**：v0.7.1 对「未提供凭证」与「凭证有效但权限不足」都返回 401 + `API_AUTH_ERROR`。
  客户端无法区分「令牌错误」与「令牌正确但无权限」，持只读令牌的用户会被误导为令牌无效。
- **复现步骤**：以只读令牌 `POST /api/storage/upload/raw_data` 上传文件。
- **预期行为**：401 = 无法确认身份（缺失 / 无效 / 过期）；403 = 身份已确认但仍不允许该操作。
- **实际行为**：返回 401 与 `API_AUTH_ERROR`，与真正的令牌错误无法区分。
- **修改范围**：`backend/security.py`（`REASON_*` 常量、状态码选择、`API_FORBIDDEN` 载荷）；
  `tests/test_v07_1_security.py`（旧断言按新契约更新）。
- **自动化测试**：`tests/test_v07_1_security.py::TestAuthMiddleware::test_readonly_token_cannot_upload`
  （断言 403 + `API_FORBIDDEN` + `reason == "insufficient_scope"`）。
- **验收证据**：安全套件 133 项全通过；拒绝响应含机器可读 `reason` 字段。
- **关联提交**：`2eb6453` + 本次更新。

## ISSUE-04 — `output_digests` / `output_artifacts` 声明但从未填充

- **问题描述**：`provenance/schema.py::ProvenanceRecord` 自 v0.7 起声明 `output_digests` 与
  `output_artifacts` 字段，但代码库中**没有任何地方写入它们**，永远为空。任务书 P1-06 要求记录
  「输出文件标识与哈希」。**有字段却不承载证据，比没有字段更具误导性**——读者会以为证据已在记录中。
- **复现步骤**：运行任一工作流，打开 `provenance.json`，检查 `nodes.<id>.output_digests`。
- **预期行为**：每个完成节点按输出端口记录内容摘要，并记录其写入的产物文件及其 SHA-256。
- **实际行为**：`output_digests == {}`，`output_artifacts == []`（`grep -rn output_digests` 仅命中 schema 定义）。
- **修改范围**：`provenance/collector.py`（`digest_value` / `file_digest` / `record_outputs`）、
  `workflow_engine/engine.py`（在节点完成时写入，并以 `artifact_start` 归属新产物）。
- **自动化测试**：`tests/test_v07_2_provenance_reproducibility.py::TestOutputDigests`
  （`test_output_digests_are_actually_populated`、`test_artifacts_are_attributed_with_a_file_digest`）。
- **验收证据**：`workflows/04_quantum_chemistry_profiling.json` 运行后 5 个节点均有摘要，
  `report` 节点的产物记录含 `exists: true` 与 `sha256:*`。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-05 — 复现摘要混入运行期身份，重复运行必然「不一致」

- **问题描述**：初次实现按输出对象的**完整序列化**计算摘要。而每个 `ScientificObject` 都带
  `id = new_id("o_")`，报告对象还带 `report_id`、内嵌运行 id 与绝对路径。因此同一确定性工作流
  两次运行的摘要**必然不同**，工具会永远报告「不一致」——这类恒真告警会让使用者学会忽略检查，
  与「可信交付」的目标相反。
- **复现步骤**：`python scripts/verify_reproducibility.py --repeat 2`（修复前）。
- **预期行为**：摘要覆盖**科学内容**；运行期身份（生成 id、时间戳、运行目录）不参与。
- **实际行为**：5/5 节点报告差异，差异内容为 `run_4cd56ceb` vs `run_e2f7f95d`、
  `rpt_0e3f8457` vs `rpt_9c435ed5`、以及不同的临时目录路径。
- **修改范围**：`provenance/collector.py`（`VOLATILE_DIGEST_KEYS`、`GENERATED_ID_RE`、
  `path_scrub_variants`、`canonical_for_digest`）、`workflow_engine/engine.py`（注入清洗词表）。
  判定依据刻意选**值形状**（`prefix_hex`）而非 `*_id` 键名，否则会连带丢弃 `dataset_id`
  这类有科学含义的标识（见 `test_digest_keeps_meaningful_identifiers`）。
- **自动化测试**：`test_digest_ignores_generated_ids`、`test_digest_still_detects_a_real_change`、
  `test_digest_keeps_meaningful_identifiers`、`test_digest_normalises_run_scoped_paths`。
- **验收证据**：`output/reproducibility.json`；2 工作流 × 2 次运行，10 个节点结果摘要完全一致。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-06 — 无自动化手段验证「声明的确定性」

- **问题描述**：节点通过 `deterministic` / `reproducibility_level` **声明**可复现，但没有任何工具
  去**验证**该声明。任务书 P1-06 验收要求「可以通过重复运行测试验证结果一致性」。
- **复现步骤**：无（该能力缺失）。
- **预期行为**：可重复运行同一工作流并逐节点比对，凡「声明为确定性却发生变化」的节点判为失败。
- **实际行为**：无此工具；确定性仅是声明。
- **修改范围**：`scripts/verify_reproducibility.py`（新增）、`scripts/quality_gate.py`
  （新增 `reproducibility_verification` 阶段）、`scripts/ci_pipeline.py`（第 6 阶段多命令支持）。
- **自动化测试**：`tests/test_v07_2_provenance_reproducibility.py::TestDeterminismClaim`（6 项）。
- **验收证据**：质量门阶段输出 `2 workflow(s) x 2 runs · 10 node results reproduced identically`。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-07 — 超时终止无自动化测试（验收缺口）

- **问题描述**：任务书 P1-03 验收标准要求「超时任务会被可靠终止或标记为终止失败」。
  `ControlledRunner` 实现了 `subprocess.TimeoutExpired` → `ExternalToolError`，但**没有任何测试**
  验证子进程真的停止。仅断言「抛异常」不足以证明任务已终止——任务可能被遗弃而继续运行。
- **复现步骤**：无（该测试缺失）。
- **预期行为**：超时后子进程停止写入，scratch 目录被清理，错误信息说明超时。
- **实际行为**：`tests/test_v07_1_capabilities.py` 原有 14 项中无超时用例
  （`grep -n "def test_" ` 可见仅覆盖白名单、argv、清理、并发）。
- **修改范围**：`tests/test_v07_1_capabilities.py` 新增两项。
- **自动化测试**：`test_timeout_terminates_the_child_and_cleans_up`（子进程心跳计数在超时后
  **停止增长**，以此证明进程确被终止，不依赖操作系统进程 API）、`test_timeout_cleans_the_scratch_directory`。
- **验收证据**：能力测试 16/16 通过。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-08 — `DependencyMissingError` 构造签名不匹配

- **问题描述**：`DependencyMissingError` 继承 `NodeExecutionError(node_id, node_type, message)`，
  但 `require_dependencies()` 以单个字符串消息调用，导致依赖缺失时抛出
  `TypeError: NodeExecutionError.__init__() missing 2 required positional arguments`。
  调用者拿到的是构造错误，而非可读的「依赖缺失」错误。
- **复现步骤**：运行声明了未安装依赖的节点（如 `ORCANode` 在未安装 ORCA 时）。
- **预期行为**：抛出携带节点标识与依赖名的 `DependencyMissingError`。
- **实际行为**：`TypeError`，且信息与依赖无关。
- **修改范围**：`workflow_engine/node_base.py`（`__init__(*args)` 兼容单参/三参两种形式；
  单参形式直接调用 `Exception.__init__`，避免出现空的 `[id:type]` 前缀）。
- **自动化测试**：`tests/test_v07_2_capability_provenance.py`（18 项全通过）。
- **验收证据**：v0.7.2 三个能力/溯源套件 58/58 通过。
- **关联提交**：`2eb6453`。

## ISSUE-09 — `git_commit()` 恒返回 `unknown`

- **问题描述**：`chemml_version.git_commit()` 写成 `["git","rev-parse","--short" if short else "HEAD"]`，
  该表达式替换的是 `--short` 而不是追加 `HEAD`，命令因此无效，异常被吞掉后返回 `"unknown"`。
  后果是所有构建元数据、安装包与发布清单都无法追溯到提交。
- **复现步骤**：`python scripts/version.py --show`。
- **预期行为**：输出真实短提交号。
- **实际行为**：`commit=unknown`。
- **修改范围**：`chemml_version.py`。
- **自动化测试**：`scripts/version.py --check`（版本一致性阶段）；
  `output/RELEASE_MANIFEST.json` 的 `commit` 字段与 `build_commit` 字段。
- **验收证据**：`python scripts/version.py --show` → `0.7.2 (Trusted Delivery Release) commit=2eb6453`。
- **关联提交**：`2eb6453`。

## ISSUE-10 — 运行时探针把 Python 3.13.14 判为超出支持范围

- **问题描述**：`desktop/src/runtime-probe.js` 的 `outOfRange()` 用完整三段版本号与
  两段边界（`3.10`–`3.13`）比较，任何形如 `3.13.14` 的版本都被判为越界，探针报告
  `python_incompatible`。
- **复现步骤**：`node desktop/src/runtime-probe.js --json --python <3.13.14 解释器>`。
- **预期行为**：`classification=ok`。
- **实际行为**：`python_incompatible`，正确环境被判为不可用。
- **修改范围**：`desktop/src/runtime-probe.js`（`outOfRange()` 仅比较 `slice(0,2)`）。
- **自动化测试**：`tests/test_v07_2_desktop_runtime.py`（21 项）。
- **验收证据**：质量门阶段输出 `classification=ok · required 8/8 from requirements.runtime.txt`。
- **关联提交**：`2eb6453`。

## ISSUE-11 — `spawnSync` 在受限主机上 `EBUSY` 并阻塞主进程

- **问题描述**：运行时探针使用 `spawnSync` 探测解释器版本。在受限主机上该调用对任何可执行文件
  都以 `EBUSY` 失败；即便成功，同步调用也会**冻结 Electron 主进程**，界面在探测期间无响应。
- **复现步骤**：在受限环境调用 `spawnSync` 执行 `node` / `cmd` / `where`。
- **预期行为**：探测异步执行，界面保持响应。
- **实际行为**：全部 `EBUSY`；探针报错。
- **修改范围**：`desktop/src/runtime-probe.js`（`runPythonProbe` 改为 Promise 化的异步 `spawn`）。
- **自动化测试**：`tests/test_v07_2_desktop_runtime.py`。
- **验收证据**：探针在本机返回 `classification=ok`，退出码 0。
- **关联提交**：`2eb6453`。

## ISSUE-12 — CI 流水线因 `sys.modules` 未注册而无法启动

- **问题描述**：`scripts/ci_pipeline.py` 用 `importlib.util` 加载质量门模块，但未将其注册进
  `sys.modules`。`@dataclass` 解析注解时按 `cls.__module__` 查表，取到 `None`，抛出
  `AttributeError: 'NoneType' object has no attribute '__dict__'`。任何 `ci_pipeline` 命令都直接崩溃。
- **复现步骤**：`python scripts/ci_pipeline.py --list`。
- **预期行为**：列出 12 个阶段。
- **实际行为**：`AttributeError`，12 阶段流水线完全不可用。
- **修改范围**：`scripts/ci_pipeline.py`（`exec_module` 前写入 `sys.modules`，失败时回滚）。
- **自动化测试**：`--list` 冒烟；CI 第 6 阶段实跑通过。
- **验收证据**：`python scripts/ci_pipeline.py --list` 正确列出 12 个阶段。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-13 — 质量门漏 `import shutil`，探针阶段 `NameError`

- **问题描述**：`scripts/quality_gate.py::stage_desktop_probe` 使用 `shutil.which("node")`，
  但模块未导入 `shutil`，阶段以 `NameError` 失败。
- **复现步骤**：运行质量门的 `desktop_runtime_probe` 阶段。
- **预期行为**：阶段执行探针并解析结果。
- **实际行为**：`[ERROR] NameError: name 'shutil' is not defined`。
- **修改范围**：`scripts/quality_gate.py`（新增 `import shutil`）。
- **自动化测试**：质量门 `desktop_runtime_probe` 阶段。
- **验收证据**：阶段返回 PASS，`classification=ok`。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-14 — 探针阶段「未读到结论却报告 PASS」

- **问题描述**：`stage_desktop_probe` 在无法解析探针输出的 JSON 时返回 **PASS**
  （`"runtime probe executed (unparsable report kept in log)"`）。真实原因是从进程输出中
  截取「从首个 `{` 到结尾」的文本，而 `_run()` 会在子进程输出后追加 `# exit=N` 尾部标记，
  使 `json.loads` 必然失败。结果是阶段**从未真正读取探针结论**却报告成功——这正是本任务书
  要消除的「看似成功但无证据」模式。
- **复现步骤**：运行 `desktop_runtime_probe` 阶段并检查日志尾部 `# exit=0`。
- **预期行为**：解析失败必须判为 harness 级错误（ERROR），而不是 PASS。
- **实际行为**：PASS，且 `ok` / 依赖计数从未被校验。
- **修改范围**：`scripts/quality_gate.py`（新增 `_extract_json()` 大括号配对提取，并跟踪字符串
  字面量以免路径中的 `}` 干扰；无法解析时返回 ERROR）。
- **自动化测试**：阶段实跑；`tests/test_v07_2_desktop_runtime.py` 覆盖探针契约。
- **验收证据**：阶段返回 `classification=ok · required 8/8 · optional 1/1`（真实读取到报告）。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-15 — `--basetemp` 剥离逻辑错误致 6 个阶段 `ValueError`

- **问题描述**：质量门为记录可复现命令而剥离 `--basetemp` 参数，代码写作
  `cmd[:cmd.index("--basetemp")]`，假设它是独立的 argv 项；实际形式为
  `--basetemp=<path>`，`index` 因找不到精确匹配的字符串而抛 `ValueError`，6 个 pytest 阶段
  全部以 ERROR 结束。
- **复现步骤**：运行质量门的任一 pytest 阶段。
- **预期行为**：剥离前缀形式的参数并记录干净的复现命令。
- **实际行为**：`ValueError: '--basetemp' is not in list`，6 个阶段 ERROR。
- **修改范围**：`scripts/quality_gate.py`（改用列表推导剥离 `--basetemp=` / `--junitxml=` 前缀）。
- **自动化测试**：质量门各 pytest 阶段。
- **验收证据**：`unit/integration/security/benchmark/desktop` 五套件全部 PASS。
- **关联提交**：本次（v0.7.2 收尾）。

## ISSUE-16 — `requirements.txt` 的 `-r` 行被当作包名解析

- **问题描述**：`requirements.txt` 只包含 `-r requirements.runtime.txt` 等引用行。许可证报告按
  逐行解析包名，把引用行当成名为 `-r requirements.runtime.txt` 的**依赖**，并判定其无法解析，
  导致 `license_sbom_report` 阶段失败。该失败是**工具缺陷**，不是真实依赖问题。
- **复现步骤**：`python scripts/license_report.py --check`。
- **预期行为**：按 `-r` 递归展开真实依赖；缺失的可选依赖记为提示而非失败。
- **实际行为**：`python-unresolved=2`，报出 phantom 依赖。
- **修改范围**：`scripts/license_report.py`（`_expand_requirements()` 跟随 `-r` 引用、
  `_PIN_RE` 避免把说明文字当包名；仅**必需**依赖缺失才失败）。
- **自动化测试**：`tests/test_v07_1_license_report.py`；质量门 `license_sbom_report` 阶段。
- **验收证据**：阶段 PASS，`faiss-cpu` 作为可选缺失项以提示形式输出。
- **关联提交**：本次（v0.7.2 收尾）。

---

## ISSUE-17 — 许可清单文档随本机构建产物变化，导致发布清单必然漂移

- **问题描述**：`docs/THIRD_PARTY_LICENSES.md` 第 5 节按当时的 `frontend/dist` 状态分支输出
  （「由 … 生成的 bundle，共 N 个文件」／「未发现预构建前端资源」），第 6 节输出清洁度扫描的
  **命中条数**。该文档的 SHA-256 被 `docs/RELEASE_MANIFEST.json` 固定，因此只要在本机重新构建
  前端或产生 `__pycache__`，文档字节就会变化——**同一个源码提交再也无法重新推导出已记录的摘要**。
  这与本版本「发布材料必须可从指定提交重新生成」的目标直接冲突。
- **复现步骤**：
  1. `python scripts/license_report.py --write`；
  2. `python scripts/release_manifest.py`（记录 `third-party-licences` 的 sha256）；
  3. 移动 `frontend/dist`（或在别处生成 `__pycache__`）后再次 `--write`；
  4. `python scripts/release_manifest.py --check`。
- **预期行为**：许可清单只承载与**发布包**和**锁定依赖图**有关的结论，与本地工作树的构建/缓存
  状态无关；`--check` 在源码未变时恒通过。
- **实际行为**：第 3 步后文档内容改变，第 4 步报
  `FAIL: manifest artefact set drifted (new=['third-party-licences'] gone=['third-party-licences'])`。
  进一步排查发现同一现象还会在质量门内部发生：门禁先运行前端生产构建、再校验发布清单，
  于是清单记录的摘要与随后重算的摘要不一致，**每次门禁必然失败**。
  （实测：同一工作树下两个变体 SHA-256 为 `93a8f06c…`／`8438bbcd…`，字节数都恰为 11914，
  说明差异只在被计入的构建产物描述上，掩盖性很强。）
- **修改范围**：`scripts/license_report.py`（§5 改为与构建状态无关的**政策性陈述**；
  §6 对 `__pycache__`/`*.pyc` 等 `_INFO_KEYS` 输出固定说明、不再输出命中数）、
  `tests/test_v07_1_license_report.py`（新增回归测试与基线重置）。
- **自动化测试**：
  `tests/test_v07_1_license_report.py::TestCheckModeDoesNotWrite::test_document_does_not_depend_on_the_local_build_output`
  （临时移除 `frontend/dist`，断言文档逐字节不变）；
  `::test_check_detects_a_tampered_artifact`、`::test_check_does_not_repair_the_tampered_artifact`
  （改为先重置基线，避免依赖套件启动时的工作树状态）。
- **验收证据**：`python scripts/quality_gate.py` → `gate: PASSED (pass=26 fail=0 skip=1)`，
  其中 `release_manifest` 与 `license_sbom_report` 均 PASS；`output/gate_logs/licence_sbom.log`。
- **关联提交**：`2eb6453` 之后的 v0.7.2 收尾提交。

---

## ISSUE-18 — 版本一致性检查覆盖不全（报 OK 但存在三处用户可见旧版本）

- **问题描述**：v0.7.2 安装包实测发现三处**用户可见**的旧版本串：启动横幅 `v0.6.0`、
  浏览器标签标题 `v0.7.1`、全部 86 个节点记录 `0.7.1`；而 `scripts/version.py --check`
  仍然报告 `OK`。检查本身没有算错，它只是**只扫了有人记得登记的文件**——典型的「证据存在但不承载结论」。
- **复现步骤**：解压 v0.7.2 安装包，访问 `/api/health`（返回 0.7.2）后打开页面与启动脚本，
  与 `python scripts/version.py --check` 的 OK 输出对照。
- **预期行为**：凡展示给用户的版本串都必须与 `chemml_version.VERSION` 一致，且检查器必须
  能对其中任意一处变旧**报告失败**。
- **实际行为**：三处漂移与「检查通过」同时存在。
- **修改范围**：`scripts/version.py`（`TEXT_TARGETS` 扩展覆盖 `.bat` / `frontend/index.html` /
  `node_registry/registry.json` / docker 文档与 compose / `desktop/package.json`；新增
  `--write`；修复 `CHANGELOG.md` 缺失时 `collect_drift` 崩溃，即 ISSUE-23）；
  `workflow_engine/node_base.py` 与 `nodes/`（节点版本改由 `chemml_version` 派生，删除 89 处
  字面量）；`node_registry/registry.json` 重生成；`start-platform.bat` 横幅；
  `frontend/index.html` 标题并重建 dist。
- **自动化测试**：`tests/test_v07_2_version_consistency.py`（把任一目标改回旧版本必须令
  `--check` 失败；含归档完整性用例）。
- **验收证据**：质量门 `version_consistency` 阶段 PASS（`OK: every artefact agrees on 0.7.2`）；
  安装副本 `/api/health` 实测 `{"status":"ok","version":"0.7.2","nodes":89}`。
- **关联提交**：`b64c176`。

## ISSUE-19 — 测试残留文件随源码包发布

- **问题描述**：`workspace/raw_data/x.csv` 是测试运行残留，却被打进源码归档，违反发布干净性
  （发布物只应包含来源可追溯的文件）。
- **复现步骤**：解压 `Chem-ML-Platform-v0.7.2.zip`，检查 `workspace/` 内容。
- **预期行为**：`workspace/` 仅保留 `.gitkeep`，运行期状态不入包。
- **实际行为**：归档含残留 CSV。
- **修改范围**：`scripts/package.py`（排除规则）；`.gitignore`。
- **自动化测试**：`tests/test_v07_2_version_consistency.py::TestArchiveDoesNotShipItsOwnChecksum::test_workspace_runtime_state_is_not_shipped`。
- **验收证据**：门禁 `release_cleanliness` 阶段 PASS；归档清单实测仅 `workspace/.gitkeep`。
- **关联提交**：`b64c176`。

## ISSUE-20 — 桌面壳前端回退路径与打包产物位置不一致

- **问题描述**：`desktop/src/main.js` 在 `resources/app/frontend-dist` 找不到前端时回退到
  `resources/frontend-dist`，而 `extraResources` 实际把前端放在 `resources/app/frontend/dist`。
  回退分支**永远不会生效**——一处为「前端缺失」准备的容错，指向一个不存在的路径。
- **复现步骤**：阅读 `desktop/package.json` 的 `extraResources` 与 `main.js` 的回退常量并对照。
- **预期行为**：回退路径与打包布局一致，或在缺失时给出可操作的错误分类。
- **实际行为**：回退路径恒不命中，前端缺失时会退化成难以诊断的空白窗口。
- **修改范围**：`desktop/src/main.js`（回退路径改为 `resources/frontend/dist`）。
- **自动化测试**：`tests/test_v07_2_desktop_runtime.py` 静态接线用例（回退路径与打包布局一致）。
- **验收证据**：门禁 `desktop_tests` 与 `desktop_runtime_probe` 阶段 PASS。
- **关联提交**：`b64c176`。

## ISSUE-21 — 解压出的副本无法自报来源提交

- **问题描述**：`chemml_version.git_commit()` 对**非 Git 工作树**（解压后的安装包、桌面壳
  payload）恒返回 `unknown`。发布报告声称产物可追溯到提交，但每一个实际分发出去的副本都无法
  自证来源——溯源链在最后一环断裂。
- **复现步骤**：解压源码归档，在归档根运行 `python -c "import chemml_version; print(chemml_version.git_commit())"`。
- **预期行为**：分发副本能 namen 自己的构建提交（打包时记录，而非现场猜测）。
- **实际行为**：输出 `unknown`。
- **修改范围**：`chemml_version.py`（`read_build_info()` / `commit_source()`；`git_commit()`
  增加 `BUILD_INFO.json` 回退）；`scripts/package.py`（归档内注入 `BUILD_INFO.json`，
  含 commit / branch / dirty / built_at）；`scripts/refresh_desktop_payload.py`（为桌面壳
  payload 盖同一印章）。
- **自动化测试**：`tests/test_v07_2_version_consistency.py::TestArchiveDoesNotShipItsOwnChecksum::test_build_stamps_provenance_into_the_archive`；
  `tests/test_v07_2_desktop_runtime.py::TestPackagedPayloadIsRunnable::test_payload_refresh_stamps_the_build_commit`。
- **验收证据**：安装副本实测自报构建提交（来源 `BUILD_INFO.json`）；桌面快照
  `refresh_desktop_payload.py --verify` 报 `build stamp present: True` / `AGREES`。
- **关联提交**：`347932d`（及 `ca1dcc8` 的工具落地）。

## ISSUE-22 — 文档声称「启动脚本注入会话令牌」，实际仅桌面壳注入

- **问题描述**：API 文档与 `backend/security.py` 的注释声称启动脚本会注入 `CHEMML_SESSION_TOKEN`。
  实际上只有 Electron 壳通过 preload 注入 `window.__CHEMML_TOKEN__`；浏览器直开模式下没有任何
  注入途径，令牌鉴权**无法启用**。文档描述了一条不存在的安全路径。
- **复现步骤**：以浏览器模式启动平台，检查 `window.__CHEMML_TOKEN__` 与令牌鉴权行为。
- **预期行为**：文档如实说明两种启动模式的能力差异。
- **实际行为**：文档暗示浏览器模式同样受令牌保护。
- **修改范围**：`backend/security.py`（注释改为如实说明）；`本地安装说明.md`（补充桌面启动方式）。
- **自动化测试**：安全套件中令牌相关用例（`tests/test_v07_2_ws_security.py` 等）不受此注释影响，
  属于文档诚实性修复。
- **验收证据**：门禁 `security_tests` 135 项 PASS；`docs_mojibake_scan` PASS。
- **关联提交**：`b64c176`。

## ISSUE-23 — 版本检查在 `CHANGELOG.md` 缺失时抛异常

- **问题描述**：`scripts/version.py` 的 `collect_drift()` 直接读取 `CHANGELOG.md`，文件缺失时
  抛异常而不是报告漂移——检查器在自己的输入不完整时崩溃，而非给出结论。
- **复现步骤**：临时移走 `CHANGELOG.md`，运行 `python scripts/version.py --check`。
- **预期行为**：缺失的登记文件按「无法核对」处理并明确报告，不抛栈。
- **实际行为**：未捕获异常。
- **修改范围**：`scripts/version.py`（`exists()` 保护）。
- **自动化测试**：`tests/test_v07_2_version_consistency.py` 套件内覆盖。
- **验收证据**：门禁 `version_consistency` 阶段 PASS。
- **关联提交**：`b64c176`。

## ISSUE-24 — 祖先 Git 仓库的 HEAD 被当作本树的构建提交

- **问题描述**：`git rev-parse` 对**任意祖先仓库**都会成功应答。`chemml_version.git_commit()`
  不校验「本树是否就是该仓库的顶层」，于是把分发副本解压进用户任意一个 Git 仓库时，平台会把
  **那个仓库的 HEAD** 当作自己的构建提交——一次教科书式的溯源造假。该缺陷由本轮桌面快照测试
  暴露：payload 落在仓库内 `output/` 下，`commit_source()` 答 `git` 而非 `BUILD_INFO.json`。
- **复现步骤**：
  1. `git init` 一个无关仓库并提交；
  2. 把 `chemml_version.py`（无 `BUILD_INFO.json`）拷进该仓库的子目录；
  3. 于该子目录运行 `python -c "import chemml_version; print(chemml_version.git_commit(), chemml_version.commit_source())"`。
- **预期行为**：只有本树根目录**本身就是** Git 顶层时才采信 Git；否则回退 `BUILD_INFO.json`，
  再否则 `unknown`。
- **实际行为**：采信祖先仓库 HEAD，`commit_source()` 答 `git`。
- **修改范围**：`chemml_version.py`（新增 `_git_repo_is_this_tree()`，以
  `git rev-parse --show-toplevel` 与 `ROOT` 比对；`git_commit()` / `commit_source()` /
  `build_stamp()` 全部改为经该守卫；重新打包无 Git 副本时向前继承原印章而非降级为 `unknown`）；
  `scripts/refresh_desktop_payload.py`（删除一处编辑残留的不可达重复代码）。
- **自动化测试**：`tests/test_v07_2_version_consistency.py::TestAncestorGitRepoIsNotClaimedAsProvenance`
  （嵌套副本无印章报 `unknown`、有印章报印章哈希、实时检出仍答 `git`；所有 git 调用以 `-C` 固定
  ——未固定时该测试曾在主仓库误建 4 个空提交，已随历史清理）。
- **验收证据**：门禁 `desktop_tests` 25 项与 `version_consistency` 阶段 PASS；
  全量 397 项测试通过。
- **关联提交**：`cfec170`。

## ISSUE-25 — 载荷刷新与构建印章互相覆盖（刷新永不收敛）

- **问题描述**：`scripts/refresh_desktop_payload.py` 的拷贝循环原样重放每一条 `extraResources`
  配对，其中包含 `BUILD_INFO.json` 条目——它指向**树根**的 `BUILD_INFO.json`，即 beforeBuild
  钩子留在树里的那一枚，通常记录比 HEAD 旧的提交。拷贝把它盖到载荷印章上之后，印章逻辑又按
  当前 HEAD 改写回去：两个步骤交替覆盖同一个文件，每次刷新都报告 2 个伪更新，文件在「钩子版」
  与「工具版」之间来回翻烙饼，刷新**永不收敛**。该缺陷由质量门禁自己在收尾重复运行中暴露：
  HEAD 越过最后一次 Electron 构建的瞬间，`desktop_tests` 阶段即以 `updated : 2` 失败。
- **复现步骤**：
  1. 构建一次 Electron（钩子在树里留下记录旧提交的 `BUILD_INFO.json`）；
  2. 把载荷内的印章改成本树从未见过的提交；
  3. 连续运行两次 `python scripts/refresh_desktop_payload.py`。
- **预期行为**：印章只由印章逻辑生成，拷贝循环不碰它；第二次刷新 `updated : 0`（收敛）。
- **实际行为**：两次都 `updated : 2`，载荷印章在钩子版与工具版之间震荡，永不收敛。
- **修改范围**：`scripts/refresh_desktop_payload.py`（拷贝循环跳过 `app/BUILD_INFO.json`
  ——印章是生成的，不是拷贝的，与 `verify()` 的既有语义一致）。
- **自动化测试**：`tests/test_v07_2_desktop_runtime.py::TestPayloadRefresh::
  test_refresh_converges_when_the_tree_stamp_is_stale`（预置陌生 commit 的印章，
  两次刷新第二次必须 `updated : 0`）；`test_refresh_leaves_an_agreeing_stamp_untouched`
  锁死反向性质。
- **验收证据**：桌面测试 35/35；真实载荷（212 条目）连续两次刷新均 `updated : 0 of 212`；
  门禁 `desktop_tests` 与 `release_manifest` 阶段 PASS；全量 410 项测试通过。
- **关联提交**：`bd2c5ee`。

## ISSUE-26 — 门禁编译阶段把测试夹具计为「一级源码文件」

- **问题描述**：`scripts/quality_gate.py` 的 `python_compile` 阶段报告
  "N first-party files compiled"，发布报告把这个数字当作「检查了什么」的证据引用。
  但其计数用 `ROOT.rglob("*.py")` 只排除了第三方/构建目录，**没有排除 `output/`**——
  而桌面 payload 测试会在 `output/pytest_gate_tmp/<run>/app/` 下构建**整棵 Python 树的副本**
  作为夹具。于是每次门禁运行后，计数就被残留夹具推高：同一棵树先后报出
  2663 → 3479 → 4296，而真实的一级源码只有约 211 个。一个会悄悄吸收测试残留的
  计数，正是「字段存在但不承载结论」那类缺陷——且它逐轮变化，无法复核。
- **复现步骤**：
  1. 跑一次质量门禁（桌面测试在 `output/pytest_gate_tmp/` 留下整树载荷副本）；
  2. 再跑一次门禁，比较两次 `python_compile` 阶段的文件数。
- **预期行为**：计数只含一级源码；`compileall` 的跳过范围与计数范围一致；
  同一棵树重复运行数字稳定。
- **实际行为**：计数含 `output/` 下的测试夹具，逐轮虚增（2663 → 3479 → 4296）。
- **修改范围**：`scripts/quality_gate.py`（`_NON_SOURCE_DIRS` 增加 `output` /
  `workspace` / `.pytest_cache` 等运行期目录；新增 `_first_party_python_files()`
  助手使计数范围可被测试；`compileall -x` 跳过模式改为**从同一集合生成**，
  两者不可能再漂移）；`tests/test_v07_2_gate_scope.py`（新增，3 项）。
- **自动化测试**：`tests/test_v07_2_gate_scope.py::TestCompileScopeCountsFirstPartySourceOnly`
  （合成树里 `output/pytest_gate_tmp/.../app/chemml_version.py` 与
  `.pytest_cache/leftover.py` 都不得被计数；实时树不得含 `output/` 下文件；
  跳过正则与计数字集合一一对应）。
- **验收证据**：新测试 3/3 通过；修复后实时树计数 **211**（稳定值），
  与 tag 时点的 209 同量级（差额为收尾阶段新增的源码文件）。
- **关联提交**：见 v0.7.2 交付收尾提交（随 ISSUE-26 修复一同提交）。

---

## 汇总

- 本表共 **26** 条 Issue。ISSUE-01…17 为 v0.7.2 实施期间发现并修复，均含完整八项字段；
  ISSUE-18…24 为交付收尾阶段（安装实测、出包、自溯源）新增，同样逐条给出八项字段；
  ISSUE-25 由质量门禁自己在收尾重复运行中抓到（刷新工具与构建钩子互相覆盖印章）；
  ISSUE-26 同样由门禁自己暴露——编译阶段的「一级源码文件数」把桌面测试留在
  `output/` 下的整树载荷夹具计了进去，数字逐轮虚增（2663 → 3479 → 4296，真实值 211）。
  全部已修复并有自动化测试或阶段级证据。
- 其中 **5 条（ISSUE-04、05、14、16、17）属于「证据类」缺陷**：字段或检查看起来存在，实际不承载
  结论，或无法被独立复核。这类缺陷不会让任何测试变红——ISSUE-17 甚至已经**被写进了发布清单**
  却仍未被发现，只能靠「按任务书逐条核对证据是否可复现」才暴露。这正是本任务书的核心要求。
- **未修复但已如实记录**的问题见 `docs/V07_2_RELEASE_REPORT.md` 的发布阻塞项清单
  （干净虚拟机安装、安装包数字签名、Linux/macOS 验证等，均标注 `不适用`/`未执行` 及原因）。
