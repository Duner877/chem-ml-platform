# V0.7 测试计划

## 1. 测试分层

| 层 | 内容 | 运行方式 | 环境标记 |
| --- | --- | --- | --- |
| 单元 | 引擎、错误模型、路径安全、溯源 schema、状态机 | pytest（离线） | 随处可跑 |
| 节点 | 全节点实例化 + 执行冒烟 | `python scripts/smoke_nodes.py` | 离线 |
| 工作流 | 六个 Demo 全图运行 | `python scripts/run_demo_workflows.py` | 离线 |
| API | FastAPI TestClient 全路由 | pytest（httpx） | 离线 |
| 安全 | 路径穿越、zip-slip、zip-bomb、上传配额、密钥脱敏 | pytest `tests/test_v07_storage.py`、`test_v07_errors.py` | 离线 |
| 前端 | `tsc --noEmit` + 生产构建 | npm run lint / build | 需 Node.js |
| 集成-真实 | 真实 LLM Provider、GPU 推理、外部量子化学软件 | 手工/可选 | **BLOCKED/可选**，缺凭据或硬件时如实标注，不用 mock 冒充 |

## 2. v0.7 新增测试文件

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_v07_storage.py` | safe_join 穿越矩阵、文件名消毒、原子写、上传配额、zip-slip/zip-bomb/条目数、工作区隔离 |
| `tests/test_v07_errors.py` | 14 个错误码位、可恢复性、建议动作、密钥脱敏、异常映射 |
| `tests/test_v07_provenance.py` | schema 完整性、环境快照、事件生命周期、provenance.json 落盘 |
| `tests/test_v07_agent_state.py` | Agent 状态机合法/非法转移、审计记录（Phase D） |
| `tests/test_v07_report.py` | MD/HTML/DOCX 导出与完整性校验（Phase F） |
| `tests/test_v07_compat.py` | v0.6 工作流 JSON 与 API 兼容回归（Phase G） |

## 3. 通过标准（质量门禁引用）

- 全部 pytest 通过（v0.6 + v0.7），无跳过被伪装为通过。
- 六个 Demo 工作流全部 completed 且 0 失败节点。
- `tsc --noEmit` 0 错误、`npm run build` 成功。
- 安全测试全部通过（穿越/zip/配额/脱敏）。
- 版本号一致性：backend/app.py、package.json、CHANGELOG 同为 0.7.x。
- 真实集成测试（LLM/GPU/外部软件）按实际环境标记 PASS / SKIPPED(原因) / BLOCKED，绝不计入通过数。

## 4. 执行记录

实际执行命令与真实结果数字记录于 `docs/V07_RELEASE_REPORT.md` §测试。
