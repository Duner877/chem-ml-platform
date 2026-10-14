# v0.7.1 安全整改与权限测试报告

> 对应任务书 §5.2「安全验收」与任务 C / D / E / F。
> 本报告只记录**已实际执行并验证**的项目；未运行项明确标注。

## 1. 整改项与实现位置

| 编号 | 任务书要求 | 实现位置 | 验证方式 |
| --- | --- | --- | --- |
| P1-01 | 上传改为流式读取、分块写入、大小与并发限制 | `storage/service.py`（`save_upload_stream` / `UploadSession`）、`backend/routers/storage.py` | `tests/test_v07_1_upload_stream.py`（9 项） |
| P1-02 | 本地 API 统一认证与权限边界 | `backend/security.py`（`AuthMiddleware` / `Permission` / `RouteRule`） | `tests/test_v07_1_security.py`（25 项） |
| P1-03 | CORS 最小来源、方法与请求头 | `backend/app.py` + `security.allowed_origins` | 同上 |
| P1-04 | 节点能力声明 + 受控外部程序执行 | `node_registry/capabilities.py`、`simulations/controlled.py` | `tests/test_v07_1_capabilities.py`（14 项） |
| P1-05 | 真实执行 / 内部近似 / 模拟 / 未执行状态区分 | `node_registry` 状态分级 + 报告证据分级章节 | `tests/test_v07_1_capabilities.py`、`tests/test_v07_1_report_provenance.py` |
| P1-09 | 上传 / 导入 / 外部程序资源边界 | `storage/service.py` 限额、`simulations/controlled.py` 超时与并发 | 上述两组测试 |
| — | Agent 授权 / 取消闭环 | `agent_runtime/tasks.py` | `tests/test_v07_1_agent_runtime.py`（12 项）、`tests/test_v07_agent_state.py` |

## 2. 本地 API 认证与权限（任务 D）

**令牌来源**（任一即可）：`X-ChemML-Token` 头、`Authorization: Bearer <token>`、`?token=<token>` 查询参数。

**权限四类**（`backend/security.py`）：

| 权限 | 含义 | 典型路由 |
| --- | --- | --- |
| `read` | 只读查询 | `GET /api/*`（默认） |
| `write` | 文件写入 / 配置变更 | `POST /api/storage/upload/*`、`PUT /api/ai/config`、`POST /api/workflows` |
| `execute` | 任务执行 | `POST /api/workflows/*/run`、`POST /api/agent/*`、`POST /api/ai/complete` |
| `external` | 可能启动外部程序 | `POST /api/simulations/run` |

**路由分类**：`classify_route(method, path)` 按**有序规则、首个匹配生效**，未匹配的默认 `read`（最小权限）。只读令牌（仅授予 `read`）无法触达 `write` / `execute` / `external` 路由 —— 由 25 项测试覆盖，包括「只读令牌访问写入路由必须 403」的端到端断言。

**CORS**：`allow_origins=security.allowed_origins`（来自 `CHEMML_ALLOWED_ORIGINS` 白名单，默认仅回环来源），`allow_methods` 显式列出 `GET/POST/PUT/DELETE/OPTIONS`，`allow_headers` 仅 `Content-Type / X-ChemML-Token / Authorization`。不再使用 `*`。

**审计**：认证失败、权限拒绝与异常操作写入 `output/security_audit.jsonl`（可审计日志），`GET /api/security/status` 如实报告安全姿态且**不泄露令牌**。

**未配置令牌时**：保持回环开发模式，并在状态接口中**明确标注为未启用认证**（不假装已保护）。

## 3. 流式上传与资源边界（任务 C）

| 限制 | 默认值 |
| --- | --- |
| 单文件大小 | 512 MB |
| 归档大小 | 1 GB |
| 归档解压后总大小 | 2 GB |
| 归档条目数 | 10 000 |
| 归档目录深度 | 16 |
| 单目录文件数 | 20 000 |
| 并发上传 | 4 |
| 单次上传墙钟超时 | 600 s |

实现要点（`storage/service.py`）：数据**逐块**写入目标同目录下 `.<name>.<rand>.part` 临时文件，**边写边校验**字节上限与墙钟超时（超限立即中止，绝不先整包读入内存）；通过校验后**原子提交**为正式文件；中断或失败自动清理半成品。保留路径白名单与包含校验，并对符号链接与目录边界有专门测试。

## 4. 受控外部程序执行（任务 E）

`simulations/controlled.py` 强制以下不变量：

1. **仅白名单可执行**：只有 `TOOL_ALLOWLIST` 中登记的程序（orca / gaussian / psi4 / cp2k / gromacs / lammps / openmm / vasp / quantum_espresso）可以被启动，其他一律 `ExternalToolNotAllowed`。
2. **显式 argv + `shell=False`**：绝不把模型生成的字符串拼进 shell。
3. **隔离工作目录**：每次运行使用独立 scratch 目录，结束清理。
4. **超时与并发限制**：信号量控制并发，超时中止。
5. **诚实缺失**：程序缺失时抛 `ExternalToolUnavailable`，由上层回退到内置引擎并标注 `internal:<engine>`；**绝不伪造外部执行成功**。`openmm` 通过 `probe_import` 实际 `import` 校验，避免把 PATH 上的任意 `python` 误判为已安装。

## 5. 节点能力声明与状态分级（任务 E / F）

`node_registry/capabilities.py` 定义五级状态：`implemented / executable / validated / experimental / unavailable`。

`node_registry.scan()` 输出（当前环境实测）：

- `availability_summary`：`executable=76, experimental=5, unavailable=8`
- `capability_summary`：`requires_network=15, requires_external_software=9, requires_gpu=4, writes_files=3, sensitive_data=1, experimental=13, nondeterministic=2`
- `missing_software_summary`：`cp2k.psmp / g16 / gmx / lmp / orca / psi4 / pw.x / vasp_std` 各 1 个节点缺失对应程序

**外部软件缺失的节点被标为 `unavailable`，不返回伪装成功的结果** —— 这是 P1-05 / F.3 的核心验收点。

## 6. 安全测试清单（实跑）

| 测试文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `tests/test_v07_1_security.py` | 25 | 路由分类、令牌校验、只读越权拒绝、CORS 白名单、配置加载、中间件端到端 |
| `tests/test_v07_1_upload_stream.py` | 9 | 分块写入、字节/超时限额、原子提交、失败清理、并发限制 |
| `tests/test_v07_1_capabilities.py` | 14 | 能力声明、状态分级、`unavailable` 诚实性、`ControlledRunner` 白名单 / argv / 隔离 / 清理 |
| `tests/test_v07_1_agent_runtime.py` | 12 | 状态转移、审批 / 拒绝 / 取消 / 重试、幂等指纹防重复 |
| `tests/test_v07_1_dataset_quality.py` | 10 | 数据元数据一致性校验 |
| `tests/test_v07_storage.py`（v0.7 基线） | — | 路径穿越、zip-slip、上传权限 |
| `tests/test_v07_agent_state.py`（v0.7 基线） | — | Agent 生命周期 |
| `tests/test_v07_errors.py`（v0.7 基线） | — | 错误脱敏 |

合计 v0.7.1 新增安全 / 可靠性用例 **70 项**（25 + 9 + 14 + 12 + 10）。

## 7. 尚未完成 / 风险记录（如实）

1. **Electron 安装包未在本环境构建**：`electron_installer_artefact` 门禁项如实 SKIP，干净机安装测试未完成（任务 A.3 未闭环）。
2. **未做操作系统级沙箱**：受 Python 子进程模型限制，插件隔离为进程级 + 权限声明，非 OS 级隔离；已记录于 `V07_KNOWN_LIMITATIONS.md`。
3. **回环开发模式无令牌**：未配置 `CHEMML_SESSION_TOKEN` 时认证关闭（仅限本机），已在状态接口与文档中明确标注。

## 8. 结论

P1 安全项（上传流式限额、API 认证与权限、CORS 最小化、受控外部程序执行、能力分级与诚实缺失）**已实现并有测试覆盖**。
P0 项中 Electron 干净机安装测试**未完成**，据此 v0.7.1 **不得标记为正式可交付版本**（见发布说明）。
