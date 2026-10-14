# Chem ML Platform 文档

| 文档 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 分层架构、引擎执行模型、事件与缓存、目录职责 |
| [node-development.md](node-development.md) | 从零编写一个科学节点：端口、参数、契约、调试 |
| [workflow-format.md](workflow-format.md) | 工作流 JSON 完整规范：节点、边、端口、参数注入 |
| [api-reference.md](api-reference.md) | REST 与 WebSocket API 逐端点参考 |
| [deployment.md](deployment.md) | 本地 / Docker / 生产部署、环境变量、插件目录 |

## 质量 · 验证 · 合规（v0.7.x）

| 文档 | 内容 |
| --- | --- |
| [V07_1_RELEASE_REPORT.md](V07_1_RELEASE_REPORT.md) | **v0.7.1 发布报告**：任务 A–L 完成矩阵、真实验证数字、未完项与结论 |
| [V07_1_SECURITY_REPORT.md](V07_1_SECURITY_REPORT.md) | 安全整改与权限测试报告：认证 / CORS / 流式限额 / 受控执行 / 能力分级 |
| [V07_1_BENCHMARK.md](V07_1_BENCHMARK.md) | 鉴定工作流**已知答案基准**：两套参考库、阴性对照、失效案例、置信度标定问题 |
| [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) | 由真实依赖元数据生成的第三方许可证清单（配根目录 `sbom.json` / `NOTICE`） |
| [V07_KNOWN_LIMITATIONS.md](V07_KNOWN_LIMITATIONS.md) | 已知限制逐条如实记录（硬件 / 外部依赖 / 设计取舍 / 基准暴露项） |
| [V07_TEST_PLAN.md](V07_TEST_PLAN.md) | 测试计划与验收红线 |
| [V07_ARCHITECTURE.md](V07_ARCHITECTURE.md) | v0.7 架构说明 |
| [V07_MIGRATION_PLAN.md](V07_MIGRATION_PLAN.md) | v0.6 → v0.7 迁移说明 |
| [V07_BASELINE_AUDIT.md](V07_BASELINE_AUDIT.md) | v0.7 开工基线审计 |
| [V07_RELEASE_REPORT.md](V07_RELEASE_REPORT.md) | v0.7.0 发布报告（版本演进档案） |
| [V07_1_COMPLETENESS_AUDIT.md](V07_1_COMPLETENESS_AUDIT.md) | v0.7.1 整改**前**差距审计（时点文档，已被发布报告取代） |
| [node-catalog.md](node-catalog.md) | 全节点能力目录（运行时状态分级，由 `scripts/node_catalog.py` 生成） |

快速上手请先阅读仓库根目录的 [README.md](../README.md)。

## 阅读顺序建议

- **只想跑通**：根 README → 快速开始。
- **想写自己的节点**：根 README → 本文档 `node-development.md` → `examples/plugins/`。
- **想把平台嵌进自己的系统**：`api-reference.md` → `node_sdk/python/README.md`。
- **想改引擎**：`architecture.md` → `workflow_engine/` 源码 → `tests/test_engine.py`。

## 术语表

| 术语 | 含义 |
| --- | --- |
| 科学对象 | 节点间传递的强类型数据：`Spectrum`、`Molecule`、`Material`、`Table`、`Image`、`SpectralMatch`、`Reaction`、`Text`、`ScientificReport` |
| 端口 | 节点上的命名连接点，带数据类型；`Any` 为通配类型 |
| 代（generation） | DAG 拓扑分层中同一层的节点集合，层内并行执行 |
| 产物 | 运行中写入 `output/<run_id>/artifacts/` 的文件，可通过 REST 下载 |
| 优雅降级 | 外部工具/API 不可用时自动回退内置引擎，并在元数据标注 `engine` |
