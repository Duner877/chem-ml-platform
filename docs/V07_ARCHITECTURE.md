# V0.7 架构设计（Desktop Scientific AI OS）

## 1. 总体分层

```
┌────────────────────────────────────────────────────────────────┐
│  desktop/  Electron 外壳                                        │
│  主进程：Python 后端生命周期 · 健康检查 · 端口协商 · IPC 网关     │
│  渲染进程：frontend/（React 18 + TS + React Flow 画布）          │
├────────────────────────────────────────────────────────────────┤
│  backend/  FastAPI REST + WebSocket                             │
│  routers: nodes · workflows · runs · ws · ai · agent · data ·    │
│           simulations · foundation · storage(v0.7) · tasks(v0.7) │
├────────────────────────────────────────────────────────────────┤
│  workflow_engine  DAG 引擎（拓扑分代 + 线程池 + EventBus + 缓存）│
│  + error_model(v0.7)  统一错误模型                               │
├───────────┬───────────────┬────────────────┬───────────────────┤
│ nodes/    │ foundation/   │ ai_runtime/    │ storage/(v0.7)     │
│ 85+ 节点  │ 基座模型注册表 │ Cloud/Local/Hybrid │ 安全文件网关   │
├───────────┴───────────────┴────────────────┴───────────────────┤
│  provenance/(v0.7)  溯源 schema + 收集器（挂到 EventBus）        │
│  report_agent + report_engine(v0.7)  MD/HTML/DOCX 导出           │
│  data_layer / simulation_runtime / database_runtime             │
└────────────────────────────────────────────────────────────────┘
```

## 2. 数据流（v0.7 保持与 v0.6 兼容）

```
React Flow 画布 ──POST /api/workflows/run──▶ WorkflowEngine
                                              │
        EventBus ──▶ WebSocket（前端实时）      │
        EventBus ──▶ ProvenanceCollector ──▶ runs/<run_id>/provenance.json
                    │
                    ▼
        节点输出 → ScientificObject（Pydantic）→ output/runs/<run_id>/artifacts/
```

## 3. v0.7 新增组件设计要点

### 3.1 storage/（§8.2）
- `WorkspaceService` 把一个根目录划成 `raw_data / cache / workflows / models / runs / uploads / reports / records` 八个白名单分类；每个分类是独立 `StorageService`，互相隔离。
- `safe_join` 用 `Path.resolve()` + `relative_to` 做根包含校验（拒绝 `..`、绝对路径、UNC、设备命名空间、symlink 逃逸）；**不是字符串前缀比较**。
- 上传：文件名消毒 + 大小配额 + SHA-256 摘要 + 原子写入（临时文件 + `os.replace`）。
- zip 解压：条目数 / 解压总量 / 嵌套深度三重上限，逐条目消毒后重拼接，防 zip-slip 与 zip-bomb。

### 3.2 error_model（§9）
- `ErrorCode` 枚举 14 个规范要求的码位；`PlatformError(ChemMLError)` 携带 message / technical / node / run_id / recoverable / suggested_action / logs。
- `redact_secrets` 在消息出口统一脱敏（sk-、Bearer、GitHub token、JWT 形态）。
- `from_exception` 把历史异常与 `SafePathError` 映射到统一码位，旧代码无需立刻重写。

### 3.3 provenance/（§11）
- `ProvenanceRecord` 数据类：输入来源与摘要、节点版本、参数快照、provider/model、外部软件版本、环境快照、时间与耗时、随机种子、警告/错误、缓存命中、fallback、设备、产物引用。
- `ProvenanceCollector` 是 EventBus 监听器：run 结束时把 `provenance.json` 写入 run 目录。节点可通过 `last_provider / last_model / fallback_used / last_device` 等属性贡献信息（渐进式增强，不破坏旧节点）。

### 3.4 desktop/（§3）
- Electron 主进程 spawn Python 后端（uvicorn），轮询 `/api/health`；健康检查通过前窗口显示启动页。
- 退出时 IPC → 主进程 kill 后端子进程树（Windows 用 taskkill /T）。
- 端口冲突：起/backend 前探测端口占用，向上报具体端口的诊断信息。
- 渲染进程加载本地 `frontend/dist`，不要求用户开浏览器。

### 3.5 Agent 状态机（§5，Phase D）
```
CREATED → PLANNING → WAITING_FOR_APPROVAL → RUNNING → VERIFYING → COMPLETED
   └──────────────────┼──────────────────▶ FAILED
                      ├──▶ CANCELLED（任意状态可入）
                      └──▶ PAUSED / WAITING_FOR_INPUT
```
工具调用全部经权限检查并审计（tool_id、参数摘要、授权结果、起止时间、输出引用、重试计数）。

## 4. 兼容性承诺

- 工作流 JSON 格式不变（v0.6 的六个 Demo 继续可跑）。
- `ScientificNode` 基类契约不变；v0.7 只做增量（能力标签等）。
- REST 既有端点路径不变；新端点全部在 `/api/` 下追加。
- 统一错误模型以「包装」方式渐进接管：未迁移的模块继续抛原异常，`from_exception` 负责映射。
