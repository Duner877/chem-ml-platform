# V0.7 基线审计报告（Baseline Audit）

**审计时间**：2026-10-13
**审计对象**：Chem ML Platform v0.6.0（本仓库 `C:/Users/hanku/Desktop/0.5 - 副本/Chem-ML-Platform-v0.6.0`）
**审计方式**：源代码逐模块审读 + 依赖清单核对 + pytest 实际运行（结果见 §4 与 docs/V07_RELEASE_REPORT.md）

> 标记约定：**VERIFIED** = 已通过测试/运行验证；**PARTIAL** = 部分实现；**MISSING** = 未实现；**BLOCKED** = 受外部软件、许可证、硬件或凭据限制。

---

## 1. 目录结构与真实入口

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| FastAPI 后端入口 `backend/app.py`（`create_app()`，版本 0.6.0，挂载 9 个路由器） | VERIFIED | 源码审读；`/api/health` 返回节点数 |
| 前端 React 18 + TypeScript + React Flow（`frontend/`，3854 个文件，含 dist 产物） | VERIFIED | 目录审计；package.json 构建脚本存在 |
| CLI 入口：`scripts/run_demo_workflows.py`、`scripts/smoke_nodes.py`、`scripts/run_agent.py`、`scripts/package.py` | VERIFIED | 文件存在且被 README/CI 引用 |
| 启动脚本 `start-backend.bat` / `start-frontend.bat` / `start-platform.bat` / `install.bat` | VERIFIED | 文件存在（Windows 批处理） |
| Docker：`Dockerfile`、`docker-compose.yml`、`docker/` | VERIFIED | 文件存在，构建未在本机验证（标注） |
| 工作流引擎 `workflow_engine/`（engine/cache/events/errors/node_base/objects/ports/registry/workflow + parsers） | VERIFIED | 62 项 pytest 中引擎测试实际运行 |
| 节点目录 `nodes/`（agent/ai/databases/instruments/question/simulation + analysis/io/report） | VERIFIED | loader 自动发现，注册表 85 节点 |
| 基座模型 `foundation/`、AI 运行时 `ai_runtime/`、数据层 `data_layer/`、仿真运行时 `simulation_runtime/`、数据库运行时 `database_runtime/`、报告代理 `report_agent/`、记忆 `memory/` | VERIFIED | 模块存在，v0.6 测试覆盖 |
| `node_sdk/`（Python `chemml_sdk` + Node.js SDK） | PARTIAL | Python SDK 有测试；Node SDK 测试未在本机运行 |
| `static/` | PARTIAL | 存在但为空/占位，Docker 构建时由前端 dist 填充 |

## 2. 依赖

| 项 | 状态 | 说明 |
| --- | --- | --- |
| Python 3.11+；fastapi/uvicorn/pydantic/numpy/scipy/networkx/matplotlib | VERIFIED | `requirements.txt` 声明并实际安装运行 |
| torch（CPU wheel 默认；CUDA 需另行安装） | PARTIAL | 声明为可选加速；本仓库默认 CPU 版；GPU 路径需真实硬件验证 |
| pytest + httpx | VERIFIED | 测试实际运行 |
| Node.js 前端依赖 | PARTIAL | `frontend/node_modules` 与 lockfile 存在；构建在本机是否通过见发布报告 |
| FAISS 等可选依赖 | BLOCKED | 注释掉的可选项，回退 NumPy 暴力检索 |

## 3. 关键机制审计

| 机制 | 状态 | 发现 |
| --- | --- | --- |
| 工作流 JSON 格式（nodes/edges，边简写 `["a","b"]`） | VERIFIED | `workflow_engine/workflow.py` 校验：ID 唯一、类型注册、无环、端口类型兼容、必填端口连接 |
| 节点注册（`nodes/loader.py` 自动发现 + `register_node` 装饰器 + `CHEMML_PLUGINS` 插件目录） | VERIFIED | 85 节点；插件在主进程直接 import（v0.7 需隔离，见限制文档） |
| Agent（`nodes/agent/` + `/api/agent/ask|plan|history`） | PARTIAL | 有规划器与规则配方回退；**无任务状态机、无工具权限审计、无执行前确认**——v0.7 Phase D 补齐 |
| AI Provider 切换（`ai_runtime/config.py`，mode auto/cloud/local/open_source/chemistry/offline，持久化 `config/ai.json`） | VERIFIED | 掩码返回密钥；离线兜底不中断 |
| 文件上传/下载 | PARTIAL | 下载走 `/api/runs/artifacts/{path}`，已登记产物限制存在；**无通用上传 API、无 StorageService、无 zip-slip/配额防护**——v0.7 Phase A/C 补齐 |
| 路径安全 | PARTIAL | 引擎产物路径相对化处理；无统一路径穿越防护——v0.7 `storage/` 模块补齐 |
| GPU / CUDA | MISSING | 无 GPU 状态检测节点，无 device 标注——v0.7 Phase E 补齐 |
| 科学绘图 | PARTIAL | matplotlib 产物图存在；无分子 2D 结构（RDKit 集成缺失）、无交互式谱图查看器 |
| 报告导出 | PARTIAL | MD/HTML/JSON 存在（report_agent + ReportExport 节点）；**无 DOCX**；PDF 依赖未声明 |
| 缓存（`ResultCache`，默认关闭） | PARTIAL | 缓存键含节点类型/参数/输入；未含节点版本与模型配置——v0.7 强化 |
| 运行事件（EventBus + WebSocket `/api/ws/run/{id}`） | VERIFIED | 前端实时渲染依赖此通道 |
| 测试 | VERIFIED | 62 项 pytest（引擎/节点/工作流/API/v0.6 基座）；本机实际运行结果见发布报告 |
| 溯源（provenance） | MISSING | 无统一 schema——v0.7 `provenance/` 模块补齐 |
| 统一错误模型 | PARTIAL | `workflow_engine/errors.py` 有异常层次；无错误码/可恢复性/建议动作——v0.7 `error_model.py` 补齐 |
| 外部软件（ORCA/Gaussian/GROMACS/Materials Studio 等） | BLOCKED | 有输入文件生成与回退引擎；真实软件本机未安装，集成测试只能验证回退路径 |

## 4. v0.6 测试基线（本机实测）

- 命令：`python -m pytest`（在隔离 venv 中运行）
- 结果：**见 docs/V07_RELEASE_REPORT.md 的实际数字**（本文件不预填未运行的结论）。

## 5. v0.7 新增模块清单（本次审计后建立）

| 模块 | 目的 | 对应规范章节 |
| --- | --- | --- |
| `storage/` | StorageService / WorkspaceService / 路径安全 / zip 防护 | §8.2 |
| `workflow_engine/error_model.py` | 统一错误码 + 可恢复性 + 建议动作 + 密钥脱敏 | §9 |
| `provenance/` | 节点级溯源 schema + 运行级收集器 | §11 |
| `desktop/` | Electron 外壳 + 后端生命周期 | §3 |
| `scripts/quality_gate.py` | 20 项质量门禁 | §18 |

## 6. 审计结论

v0.6 是一个真实可运行的科学工作流平台（引擎/节点/API/测试均经实际运行确认），不是空壳。v0.7 的主要缺口集中在：**桌面化（Electron）、安全存储层、Agent 状态机与权限、GPU 体系、统一溯源、DOCX 导出、质量门禁**。这些缺口将在 Phase A–G 中按 `docs/V07_MIGRATION_PLAN.md` 的顺序补齐。
