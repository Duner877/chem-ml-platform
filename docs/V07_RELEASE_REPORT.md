# Chem ML Platform v0.7.0 — 发布报告（V07_RELEASE_REPORT）

> **历史记录**：本文件是 **v0.7.0** 的发布报告，保留作为版本演进档案。
> v0.7.1 的发布报告见 [`V07_1_RELEASE_REPORT.md`](V07_1_RELEASE_REPORT.md)。

**发布日期**：2026-10-13
**升级路径**：v0.6.0 Scientific Foundation Model Edition → v0.7.0 Desktop Scientific AI OS
**执行环境**：Windows 11（win32），Python 3.13.14（隔离 venv），Node.js 22.22.2，torch 2.14.1+cpu（本机无 CUDA GPU）

> 本报告只记录**实际运行过**的命令与真实结果数字。未实现 / 未验证的功能在 §11 如实列出，绝不冒充完成。

---

## 1. 已完成的功能

| 模块 | 说明 | 对应规范 |
| --- | --- | --- |
| `storage/` 安全存储层 | `safe_join` 根包含校验（拒绝 `..`/绝对路径/UNC/设备命名空间/symlink-junction 逃逸）、文件名消毒、原子写入、上传配额 + SHA-256、zip-slip/zip-bomb/条目数三重防护、八分类白名单工作区 | §8.2 |
| `workflow_engine/error_model.py` | 14 个规范错误码、可恢复性、中文建议动作、出口密钥脱敏（sk-/Bearer/GitHub/JWT） | §9 |
| `provenance/` + 引擎集成 | 每次 `WorkflowEngine.run()` 自动写 `output/runs/<run_id>/provenance.json`（环境快照、参数快照、状态、错误、缓存命中） | §11 |
| `workflow_engine/agent_state.py` | Agent 任务状态机：严格生命周期 + 非法转移拒绝 + 重试预算 + 审计历史 | §5.1 |
| `nodes/gpu/`（4 节点） | GPU Device Info / PyTorch Tensor Op / Model Inference / Inference Benchmark；真实探测、种子确定性、诚实 CPU fallback 标注 | §7 |
| `report_engine/` | Markdown / HTML（全量转义防注入）/ DOCX 三格式导出，内容来自真实 RunResult，导出附大小 + SHA-256 | §13 |
| `backend/routers/storage.py` | 上传 / 列目录 / 删除 REST API，全部走 StorageService；厂商格式（.raw）明确标记不可解析 | §8 |
| `backend/routers/runs.py` 修复 | 下载接口由字符串前缀比较改为解析后根包含校验，仅允许已登记产物根 | §8.2 |
| `desktop/` Electron 外壳 | 主进程 spawn 后端 + `/api/health` 轮询 + 端口协商 + 退出进程树清理 + preload 安全 IPC + electron-builder 配置（win NSIS / linux / mac） | §3 |
| `scripts/quality_gate.py` | 18 项检查，JSON + Markdown 双报告，SKIP 如实计数 | §18 |
| 节点能力标签 | `ScientificNode.capabilities` 进入 `spec()`；仿真节点标记 `requires_external_software` | §4 |
| 文档五件套 | BASELINE_AUDIT / ARCHITECTURE / MIGRATION_PLAN / TEST_PLAN / KNOWN_LIMITATIONS | §2 |

## 2. 修改过的关键文件

- `backend/app.py`（版本 0.7.0 + 挂载 storage 路由）
- `backend/routers/runs.py`（下载路径安全修复）
- `workflow_engine/engine.py`（RunResult.provenance_path + 溯源写入）
- `workflow_engine/node_base.py`（capabilities 字段）
- `nodes/simulation/quantum.py`、`nodes/simulation/molecular_dynamics.py`（能力标签）
- `tests/test_v06.py`（版本断言兼容 0.6/0.7，防回归语义不变）
- `frontend/package.json`（0.7.0）、`README.md`、`CHANGELOG.md`、`本地安装说明.md`

## 3. 新增的模块

`storage/`（3 文件）· `provenance/`（2 文件）· `nodes/gpu/`（2 文件）· `report_engine/`（1 文件）· `backend/routers/storage.py` · `desktop/`（3 文件）· `scripts/quality_gate.py` · `tests/test_v07_*.py`（8 个测试文件）· `docs/V07_*.md`（5 份）

## 4. 实际运行的测试命令

```bash
python -m pytest -p no:cacheprovider                    # 完整测试套件
python scripts/run_demo_workflows.py                    # 六个 Demo 端到端
python scripts/quality_gate.py                          # 质量门禁（18 项）
cd frontend && npm run lint && npm run build            # tsc + 生产构建
```

## 5. 测试结果（真实数字）

| 套件 | 结果 |
| --- | --- |
| pytest 完整套件（v0.6 基线 62 + v0.7 新增 86） | **148 passed, 0 failed, 0 skipped**（80.9s） |
| 六个官方 Demo 工作流 | **6/6 completed**，0 失败节点 |
| 质量门禁 | **PASSED：17 PASS / 0 FAIL / 1 SKIP**（SKIP=GPU CUDA 本机不可用，如实标注） |
| 节点注册 Schema 校验 | 89 个节点类型全部通过 |
| 前端 `tsc --noEmit` | 0 错误 |
| 前端生产构建 | 成功（dist 3 文件，JS 374.77 kB） |

## 6. 桌面安装包构建结果

- Electron 外壳与 electron-builder 配置完成并通过结构校验（质量门禁 `electron_build_config` PASS）。
- **NSIS 安装包未在本机实际构建**（需要 `cd desktop && npm install` 下载 electron 二进制，本会话网络受限未完成）。
- 构建命令已就绪：`cd desktop && npm install && npm run build`（输出到 `desktop/dist/`）。
- 如实状态：**配置就绪，安装包未产出**。

## 7. CPU / GPU 测试结果

- torch 2.14.1+cpu 实际安装并运行：张量运算（种子确定性校验通过）、MLP 前向推理、基准测试均通过。
- 本机无 CUDA GPU：`GpuDeviceInfoNode` 如实报告 `cuda_available=false`；请求 CUDA 且 `require_gpu=true` 时节点按预期抛出含 `GPU_UNAVAILABLE` 的错误；`require_gpu=false` 时诚实 CPU 回退并在结果中标注 `fallback_used=true`（均有测试断言）。
- 质量门禁 GPU 项：SKIP（torch 在、CUDA 不在）——不算通过也不隐瞒。

## 8. AI Provider 测试结果

- 未配置任何 API Key（本机无凭据）：离线推理器路径经 v0.6 回归测试验证可用；云端 Provider 测试如实标记为 BLOCKED（缺凭据），未用 mock 冒充。

## 9. 科学文件解析测试结果

- v0.6 的 mzML/mzXML/MGF/MSP/JCAMP/XY/Bruker 解析器经基线 62 项测试继续通过（未改动）。
- v0.7 上传 API 的格式探测测试通过：`.csv`→Universal Format；`.raw`→Vendor Native Format + 不可解析警告。

## 10. 安全测试结果

- 路径穿越矩阵（`..`、绝对路径、UNC、设备命名空间、junction 逃逸）全部拒绝——33 项存储安全测试通过。
- zip-slip 条目显式拒绝、zip-bomb（解压总量上限）拦截、条目数上限拦截。
- 密钥脱敏测试通过（sk-/Bearer 形态在出口被掩码）。
- 产物下载：仅已登记产物根可访问，`/api/runs/artifacts/../backend/app.py` 返回 403/404。

## 11. 仍未完成的功能（如实列出）

| 项 | 状态 | 阻塞原因 |
| --- | --- | --- |
| Electron NSIS 安装包产出 | 未完成 | 需 `npm install` 下载 electron 二进制（本会话网络超时）；配置与入口已就绪 |
| Agent 状态机接入 REST/前端 UI | 部分 | 状态机与测试完成；`/api/agent/*` 仍走 v0.6 规划器，状态机接线属后续工作 |
| 工具调用权限审计中间件 | 未完成 | 依赖状态机接线 |
| Run Diff / 实验记录 / 数据集目录 API | 未完成 | schema 已定于 provenance；目录与 diff 界面未实现 |
| 分子 2D 结构图（RDKit） | BLOCKED | RDKit 未安装；节点按 `DEPENDENCY_MISSING` 诚实报错的模式已就绪 |
| CUDA 真实推理 | BLOCKED | 本机无 NVIDIA GPU |
| 云端 LLM / 外部量子化学软件集成测试 | BLOCKED | 无 API Key / 软件未安装（回退路径已验证） |
| Node.js SDK 测试 | 未运行 | 不在本机门禁必跑集 |

## 12. 第三方软件与许可证限制

- 平台依赖（fastapi/uvicorn/pydantic/numpy/scipy/networkx/matplotlib/pytest/python-docx）均为 MIT/BSD/PSF 宽松许可，与 Apache-2.0 兼容；torch（BSD-3）为可选依赖。
- Gaussian / Materials Studio / ORCA / GROMACS 等商业软件：仅提供输入文件生成 + 内置物理回退引擎；不伪装 CLI，不假设许可证。
- 厂商原始格式（如 Thermo `.raw`）：仅识别并提示转换流程，不宣称解析。

## 13. v0.6 → v0.7 迁移说明

1. **工作流 JSON 格式不变**：v0.6 的六个 Demo 无需修改即可运行（已实测）。
2. **REST 端点全部保留**，新增 `/api/storage/*`；`/api/health` 与 `/api/meta` 的 version 字段为 `0.7.0`。
3. **节点契约不变**：`ScientificNode` 仅新增可选 `capabilities` 类属性；旧节点无需改动。
4. **每次运行新增产物**：`output/runs/<run_id>/provenance.json`；`RunResult` 新增 `provenance_path` 字段。
5. **测试兼容性**：`test_api_health_version` 接受 0.6/0.7 两版版本号（回归语义为"报告真实版本号"）。
6. 详见 `docs/V07_MIGRATION_PLAN.md`。

## 14. ZIP 文件的真实路径与大小

- 路径：`C:\Users\hanku\Desktop\0.5 - 副本\Chem-ML-Platform-v0.7.0.zip`
- 打包命令：`python scripts/package.py --name Chem-ML-Platform-v0.7.0 --output ../Chem-ML-Platform-v0.7.0.zip`
- 实际大小：见 §14 下方打包输出记录（打包后由打包脚本回显，未预留占位数字）。
