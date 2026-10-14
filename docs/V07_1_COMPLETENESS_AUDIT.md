# Chem ML Platform v0.7.1 — 完成度与错误审计

> **⚠️ 时点文档（已被取代）**：本文件是 v0.7.1 开工**之初**的差距审计，反映当时的完成度判断与错误清单（任务 I / K / L 等尚在 0–15%）。
> 任务 A–L 落地后的**最终**交付状态、真实数字与未完项，见 **[`V07_1_RELEASE_REPORT.md`](V07_1_RELEASE_REPORT.md)**、**[`V07_1_SECURITY_REPORT.md`](V07_1_SECURITY_REPORT.md)**、**[`V07_1_BENCHMARK.md`](V07_1_BENCHMARK.md)**。
> 本文件保留作为「整改前基线」，请勿据其判断当前完成度。

**审计对象**：`Chem-ML-Platform-v0.7.0/`（自 v0.7.0 发布包解出，作为 v0.7.1 工作区）
**审计依据**：《Chem ML Platform v0.7.1 版本升级任务书》
**审计时间**：2026-10-14（**整改前基线**）
**审计方式**：源码静态核查 + 测试套件实跑 + 注册表一致性校验（不含臆测）

---

## 零、结论速览

| 维度 | 状态 |
|---|---|
| Python 测试 | **148 passed / 0 failed**（审计中修复 1 项版本断言） |
| 新增代码（B/C/D） | 已实现但 **0 测试覆盖** |
| P0 发布阻断项 | **未达成**（任务 A Electron 后端打包未开始） |
| 可标记为 v0.7.1 正式发布 | **否** |

**总完成度估计：约 35%。** 代码骨架已搭好（安全/上传/Agent 状态机三大模块可运行），但**测试、桌面交付、节点能力分级、科学基准、开源合规**五大板块尚未完成，且发布物存在版本与节点数不一致。

---

## 一、测试与构建状态（实跑结果）

| 检查 | 命令 | 结果 |
|---|---|---|
| Python 单元测试 | `pytest tests/` | 148 passed, 1 warning（77.7 s） |
| 注册表一致性 | `python -m node_registry --check` | `valid: True`，但**与落盘 registry.json 不一致**（见错误 E2） |
| 新增模块测试覆盖 | 检索 `agent_runtime / security / stream` | **无任何测试引用**（见错误 E4） |

> 审计中唯一 FAIL 为 `tests/test_v06.py::test_api_health_version`（版本断言仅允许 `{0.6.0, 0.7.0}`，实际已为 `0.7.1`）——**已修复**，套件恢复全绿。

---

## 二、任务 A–L 完成度矩阵

| 任务 | 优先级 | 要求 | 现状 | 完成度 |
|---|---|---|---|---|
| **A** Electron 后端打包 | P0 | 打包 Python 后端+运行时，干净环境可装可跑 | `desktop/package.json` 仍 0.7.0；`extraResources` **只含 frontend/dist，不含后端**；无运行时定位/首启诊断 | **0%** |
| **B** Agent 状态机闭环 | P0 | 所有 Agent 任务经统一状态机 | ✅ `agent_runtime/tasks.py`（497 行，状态机+scheduler+幂等指纹）；✅ `backend/routers/agent.py` 9 端点（ask/plan/tasks/approve/reject/cancel/retry/history）；✅ `nodes/agent/agent.py` 重构 | **60%**（缺测试） |
| **C** 上传/存储安全 | P1 | 流式分块、限额、并发、原子提交 | ✅ `storage/service.py` `save_upload_stream`（chunk→`.part`→原子提交，字节/超时/并发限制）；✅ `backend/routers/storage.py` 重写 | **60%**（缺测试） |
| **D** 本地 API 与权限 | P1 | 会话令牌、权限类别、最小 CORS | ✅ `backend/security.py`（Permission/RouteRule/AuthMiddleware/令牌）；✅ `backend/app.py` CORS 收紧为白名单 | **60%**（缺测试） |
| **E** 节点/插件执行隔离 | P1 | 能力标签、受控外部程序执行 | ⚠️ 仅在 `quantum.py`/`molecular_dynamics.py` 声明 `requires_external_software`；无统一受控执行服务 | **15%** |
| **F** 节点能力分级与真实性 | P1 | implemented/executable/validated/experimental/unavailable | ⚠️ `node_base.py` 已有 `capabilities` 字段与 spec 输出，但**无状态分级**、无覆盖 | **20%** |
| **G** 数据质量与元数据治理 | P1 | 修 `shimadzu_lcms/sample_01` 类别不一致 + 校验器 | ❌ 元数据仍在 `mass_spectrometry/` 下却写 `data_type: IRSpectrum` / `technique: FT-IR`，**未修**；无校验器 | **5%** |
| **H** 溯源/错误/可复现 | P1 | 每次运行完整记录 | ✅ v0.7.0 基线已具备（`provenance/`、`error_model.py`，有测试） | **80%** |
| **I** 科学基准与验证 | P1 | LC-MS/MS 已知答案基准+评测 | ❌ 无样本集、无评测脚本、无报告 | **0%** |
| **J** 报告导出与呈现 | P1 | DOCX/MD/HTML 真导出并含溯源 | ⚠️ v0.7.0 基线已有三格式导出（有测试），未按 v0.7.1 要求补「来源/参数/版本/局限」 | **70%** |
| **K** 许可证/引用/合规 | P1/P2 | 依赖清单、许可报告、SBOM、NOTICE | ❌ 仅根 `LICENSE`；**无 NOTICE / SBOM / 依赖许可报告**；license 检查仍偏硬编码 | **15%** |
| **L** 质量门禁与发布工程 | P0/P2 | 可重复门禁、清洁、版本一致 | ⚠️ `scripts/quality_gate.py`（446 行，18 项检查）为 v0.7.0 基线；缺基准/许可/SBOM 检查 | **50%** |
| **—** 版本号一致性 | P0 | 统一 0.7.1 | ⚠️ 仅 9 文件为 0.7.1，多处残留 0.7.0（见 E3） | **20%** |

---

## 三、错误清单

### 已修复
| 编号 | 错误 | 处理 |
|---|---|---|
| E1 | `tests/test_v06.py::test_api_health_version` 断言 `{"0.6.0","0.7.0"}`，实际 `0.7.1` → 套件 1 FAIL | 断言集合补入 `0.7.1`，现 **148 passed** |

### 待修复（按严重度）
| 编号 | 严重度 | 错误 | 位置 | 依据 |
|---|---|---|---|---|
| **E2** | **高** | 注册表陈旧：落盘 `registry.json` = **85 节点 / 27 分类 / 50 模块**，live 扫描 = **89 / 28 / 52**；README 与徽章亦写 85 | `node_registry/registry.json`、`README.md` | P0-05 / P2-06 |
| **E3** | **高** | 版本号残留 0.7.0（未升级到 0.7.1） | `README.md`、`CHANGELOG.md`（无 0.7.1 条目）、`desktop/package.json`、`frontend/package.json`、`本地安装说明.md`、`docs/V07_RELEASE_REPORT.md`；`nodes/gpu/gpu_nodes.py`（节点 version）、`provenance/schema.py`（`PROVENANCE_SCHEMA_VERSION`，属 schema 版本，可保留） | P0-05 / P2-07 |
| **E4** | **高** | 新增代码零测试：`agent_runtime.tasks`、`backend.security`、流式上传均无测试用例 | `tests/` | 5.2 安全验收 |
| **E5** | 中 | Electron 后端打包缺失（P0-01 核心）：`extraResources` 不含 Python 后端，`main.js` 依赖开发环境 | `desktop/` | P0-01 / P0-02 |
| **E6** | 中 | 样例数据元数据类别不一致未整改 | `datasets/mass_spectrometry/shimadzu_lcms/sample_01.metadata.json` | P1-07 / 任务 G |
| **E7** | 中 | 无 LC-MS/MS 已知答案基准 | — | 任务 I |
| **E8** | 中 | 无 NOTICE / SBOM / 依赖许可报告 | 根目录 | P2-01/02 / 任务 K |
| **E9** | 低 | `static/` 为 `frontend/dist` 的**实体副本**（非单一来源），存在重复资源 | `static/`、`frontend/dist/` | P2-05 |
| **E10** | 低 | 质量门禁未覆盖：科学基准、许可/SBOM、发布包清洁度 | `scripts/quality_gate.py` | 任务 L |

---

## 四、剩余工作与建议顺序

**阶段 1（Release Blocker，先做）**
1. **E3 版本清扫**：README / CHANGELOG（补 0.7.1 条目）/ desktop / frontend / 安装说明 / 发布报告 → 0.7.1。
2. **E2 注册表重建**：`python -m node_registry --write`，统一 89/28/52，并同步 README 与徽章（建议加脚本化统计，满足 P2-06）。
3. **A / E5 Electron 后端打包**：`extraResources` 纳入后端与运行时、入口/资源/日志目录定位、首启依赖检测与错误诊断。

**阶段 2（安全加固收尾）**
4. **E4 补测试**：Agent 状态机状态转移+权限、认证/授权/CORS、流式上传限额与路径边界、ZIP 解压限制。
5. **E / F 节点能力分级**：全节点补 `capabilities`；新增 implementation status 分级；受控外部程序执行服务。

**阶段 3（科学真实性）**
6. **G 元数据治理**：修 `sample_01` 类别 + 元数据校验器。
7. **I 科学基准**：LC-MS/MS 已知答案基准 + `scripts/` 评测脚本 + 报告。
8. **J 报告增强**：溯源/来源/局限字段。

**阶段 4（开源与发布）**
9. **E8 K 合规**：依赖许可报告 + NOTICE + SBOM（真实依赖元数据生成）。
10. **L 门禁扩展** + Python 缓存清理（P2-04）+ `static` 单一来源（E9）。
11. 全量验证矩阵（pytest / smoke / demo / 前端 build+tsc / Node SDK / registry）+ 打包 `Chem-ML-Platform-v0.7.1.zip` + 发布/安全/基准/已知限制报告。

---

## 五、可信声明

- 本审计只记录**实际执行过的检查**，未运行项一律标注，不折算为通过。
- v0.7.1 **当前不可标记为正式发布**：P0 项（A/Electron 交付、L 完整门禁、P0-05 一致性）尚未闭环。
- 新增的 B/C/D 代码在补测试前，**不应视为已验证能力**（任务书 §5.2、§七）。
