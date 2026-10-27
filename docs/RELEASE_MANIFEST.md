# Chem ML Platform v0.7.4 — Release Manifest

- **codename**: Trusted Delivery Release
- **commit**: `26677fd`
- **python**: 3.13.14
- **generated**: 2026-10-27T12:04:26+00:00
- **declared / built / tested / published**: 21 / 18 / 17 / 0

> `published` 仅在本机向发布渠道实际上传后才为真。本清单由本地构建生成，因此除已明确标注者外，全部产物均为**已构建、未发布**。

| 产物 | 类型 | 状态 | 大小 | SHA-256 | 文件 |
| --- | --- | --- | --- | --- | --- |
| 源码归档（可直接 push 到 GitHub 的完整源码树） | 源码归档 | 已构建 · 已测试 | 2005 KiB | `3c9d294f9baebd57…` | `C:/Users/hanku/Desktop/Chem ML Platform/01-源码/Chem-ML-Platform-v0.7.4.zip` |
| Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针） | 安装包 | 未构建 | — | `—` | `（缺失）` |
| NSIS 差分更新块映射（由 electron-builder 同步产出） | 安装包 | 未构建 | — | `—` | `（缺失）` |
| 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单 | SBOM | 已构建 · 已测试 | 106 KiB | `7b1148dad1b744c5…` | `sbom.json` |
| 质量门禁机器可读结果（逐步骤证据、退出码、日志路径） | 报告 | 已构建 · 已测试 | 14 KiB | `bd9fd73979cb8d1a…` | `output/quality_gate.json` |
| 质量门禁人工可读报告 | 报告 | 已构建 · 已测试 | 11 KiB | `1186bae982e8f11a…` | `output/quality_gate.md` |
| 12 阶段 CI 流水线结果（每阶段独立退出码） | 报告 | 未构建 | — | `—` | `（缺失）` |
| 第三方许可证清单（由真实依赖元数据生成） | 合规 | 已构建 · 已测试 | 14 KiB | `2a91526f05fe7472…` | `docs/THIRD_PARTY_LICENSES.md` |
| 源码/依赖/数据集/模型来源与许可记录 | 合规 | 已构建 · 已测试 | 14 KiB | `fe33f0ecb1b5bcff…` | `docs/PROVENANCE.md` |
| 根 NOTICE（分发组件归属声明） | 合规 | 已构建 · 已测试 | 9 KiB | `ceba37b6f4e08b64…` | `NOTICE` |
| 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率） | 报告 | 已构建 · 未测试 | 9 KiB | `3658df1be7b08e40…` | `docs/V07_2_SYNTHETIC_BENCHMARK.md` |
| 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据） | 报告 | 已构建 · 已测试 | 16 KiB | `6f0ed1944e530701…` | `docs/node-catalog.md` |
| Python 依赖锁定文件（含可复现安装所需的精确版本） | 运行时依赖 | 已构建 · 已测试 | 1 KiB | `ee5a15f7058af12d…` | `requirements.lock` |
| 前端依赖锁文件（npm ci 使用的确定性依赖图） | 运行时依赖 | 已构建 · 已测试 | 44 KiB | `abf8189cc012b05c…` | `frontend/package-lock.json` |
| 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包） | 开发环境 | 已构建 · 已测试 | 21 KiB | `347091c24dcdd022…` | `desktop/src/runtime-probe.js` |
| 结果复现验证报告（逐节点输出摘要，重复运行比对） | 报告 | 已构建 · 已测试 | 2 KiB | `1e50d806a3d9f7ec…` | `output/reproducibility.json` |
| 插件与外部程序执行边界规范（P1-03 / P2-04） | 合规 | 已构建 · 已测试 | 10 KiB | `2868c3e7787562c2…` | `docs/V07_2_PLUGIN_SPEC.md` |
| v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录） | 报告 | 已构建 · 已测试 | 37 KiB | `0b84bfa610efcc25…` | `docs/V07_2_RELEASE_REPORT.md` |
| 问题记录表（每条含任务书 §三 要求的八项字段） | 合规 | 已构建 · 已测试 | 37 KiB | `ea0c905bdcdeddd0…` | `docs/V07_2_ISSUE_LOG.md` |
| 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED） | 报告 | 已构建 · 已测试 | 2 KiB | `e862f3e7f7ea5b9f…` | `docs/V07_2_CLEAN_ENV_TEST.md` |
| 真实数据验证计划（明确标注为计划，尚未执行） | 报告 | 已构建 · 已测试 | 6 KiB | `226e588b50068abd…` | `docs/V07_2_REAL_DATA_VALIDATION_PLAN.md` |

## 逐项明细

### `source-archive` — 源码归档（可直接 push 到 GitHub 的完整源码树）

- 构建方式：`python scripts/package.py --name Chem-ML-Platform-v{version} --output ../Chem-ML-Platform-v{version}.zip`
- 路径：`C:/Users/hanku/Desktop/Chem ML Platform/01-源码/Chem-ML-Platform-v0.7.4.zip`
- 构建 commit：`26677fd`
- SHA-256：`3c9d294f9baebd5780262bed7d11f62fc0ed088a621154985823453c54bf649a`
- 大小：2053471 B（2005.3 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/RELEASE_MANIFEST.md, SHA256SUMS
- 发布说明：未从本机上传到任何发布渠道

### `windows-installer` — Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针）

- 构建方式：`cd desktop && npm install && npm run build`
- 路径：`（缺失）`
- 构建 commit：`—`
- SHA-256：`—`
- 构建 / 测试 / 发布：否 / 否 / 否
- 发布说明：未从本机上传到任何发布渠道

### `installer-blockmap` — NSIS 差分更新块映射（由 electron-builder 同步产出）

- 构建方式：`cd desktop && npm run build`
- 路径：`（缺失）`
- 构建 commit：`—`
- SHA-256：`—`
- 构建 / 测试 / 发布：否 / 否 / 否
- 发布说明：未从本机上传到任何发布渠道

### `sbom` — 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单

- 构建方式：`python scripts/license_report.py --write`
- 路径：`sbom.json`
- 构建 commit：`26677fd`
- SHA-256：`7b1148dad1b744c59dfb3a21c770925fd42d67b0e8c87872c2502e46baae5582`
- 大小：108824 B（106.3 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/THIRD_PARTY_LICENSES.md
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-json` — 质量门禁机器可读结果（逐步骤证据、退出码、日志路径）

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.json`
- 构建 commit：`26677fd`
- SHA-256：`bd9fd73979cb8d1a499789b841b96da6a1598b6ee756cd8f3a164b53713cc1b1`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：14177 B（13.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-md` — 质量门禁人工可读报告

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.md`
- 构建 commit：`26677fd`
- SHA-256：`1186bae982e8f11ad31071fce1c3758d540591c1a36cb0adf6918d77646b0989`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：10970 B（10.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `ci-pipeline-json` — 12 阶段 CI 流水线结果（每阶段独立退出码）

- 构建方式：`python scripts/ci_pipeline.py`
- 路径：`（缺失）`
- 构建 commit：`—`
- SHA-256：`—`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 构建 / 测试 / 发布：否 / 否 / 否
- 发布说明：未从本机上传到任何发布渠道

### `third-party-licences` — 第三方许可证清单（由真实依赖元数据生成）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`docs/THIRD_PARTY_LICENSES.md`
- 构建 commit：`26677fd`
- SHA-256：`2a91526f05fe74720f68f9db3fd3a17d5e9835eef0138debda31b975886a191a`
- 大小：14048 B（13.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `provenance-record` — 源码/依赖/数据集/模型来源与许可记录

- 构建方式：`(maintained by hand; see docs/PROVENANCE.md)`
- 路径：`docs/PROVENANCE.md`
- 构建 commit：`26677fd`
- SHA-256：`fe33f0ecb1b5bcfff211be74b825f7db25b10666ff1bd985d58af0b13184192d`
- 大小：13857 B（13.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `notice` — 根 NOTICE（分发组件归属声明）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`NOTICE`
- 构建 commit：`26677fd`
- SHA-256：`ceba37b6f4e08b6412517b0615241783361ca451aedc0667260d1fafb0ac95ac`
- 大小：8797 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `synthetic-benchmark-report` — 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率）

- 构建方式：`python scripts/benchmark_lcms.py`
- 路径：`docs/V07_2_SYNTHETIC_BENCHMARK.md`
- 构建 commit：`26677fd`
- SHA-256：`3658df1be7b08e403dfe8237d03b4c5b6a33be0b2983d242dacf07b329718661`
- 大小：8813 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 否 / 否
- 测试说明：缺少证据文件: output/benchmark_lcms.json
- 发布说明：未从本机上传到任何发布渠道

### `node-capability-catalogue` — 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据）

- 构建方式：`python scripts/node_catalog.py --write`
- 路径：`docs/node-catalog.md`
- 构建 commit：`26677fd`
- SHA-256：`6f0ed1944e5307019f70e66a772f6f14d0e1dbab58c887ea780a160b355ae2df`
- 大小：16784 B（16.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `python-dependency-lock` — Python 依赖锁定文件（含可复现安装所需的精确版本）

- 构建方式：`pip install -r requirements.txt && pip freeze (see docs/V07_2_DEPENDENCIES.md)`
- 路径：`requirements.lock`
- 构建 commit：`26677fd`
- SHA-256：`ee5a15f7058af12d1a8f27060caed436fd86a7411f8fd1c396ec1bc15a523d15`
- 大小：1499 B（1.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `frontend-dependency-lock` — 前端依赖锁文件（npm ci 使用的确定性依赖图）

- 构建方式：`npm install (committed lockfile)`
- 路径：`frontend/package-lock.json`
- 构建 commit：`26677fd`
- SHA-256：`abf8189cc012b05cbb50b5bd1f0878d4e2821b684a3bdfc900ce1a1dc411f483`
- 大小：45443 B（44.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `desktop-runtime-probe` — 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包）

- 构建方式：`(first-party source)`
- 路径：`desktop/src/runtime-probe.js`
- 构建 commit：`26677fd`
- SHA-256：`347091c24dcdd022305d905a3339c39001dd57f13838f04630558dac6ce774e6`
- 大小：21712 B（21.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_desktop_runtime.py
- 发布说明：未从本机上传到任何发布渠道

### `reproducibility-report` — 结果复现验证报告（逐节点输出摘要，重复运行比对）

- 构建方式：`python scripts/verify_reproducibility.py --repeat 2`
- 路径：`output/reproducibility.json`
- 构建 commit：`26677fd`
- SHA-256：`1e50d806a3d9f7ecca7b4e0e3609a2bfa507a0bb567aba38a409f988992eb0cf`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：2026 B（2.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_provenance_reproducibility.py
- 发布说明：未从本机上传到任何发布渠道

### `plugin-spec` — 插件与外部程序执行边界规范（P1-03 / P2-04）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_PLUGIN_SPEC.md`
- 构建 commit：`26677fd`
- SHA-256：`2868c3e7787562c2b8c377d289fa341e6625fd6f4dd1bcd9fd2e9379812afd7a`
- 大小：10003 B（9.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_1_capabilities.py
- 发布说明：未从本机上传到任何发布渠道

### `release-report` — v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录）

- 构建方式：`(maintained by hand; numbers quoted from output/quality_gate.json)`
- 路径：`docs/V07_2_RELEASE_REPORT.md`
- 构建 commit：`26677fd`
- SHA-256：`0b84bfa610efcc25f901467c5aaa5b050b1a083b8e8bb4c4327013ad81b1537c`
- 大小：37630 B（36.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/quality_gate.json
- 发布说明：未从本机上传到任何发布渠道

### `issue-log` — 问题记录表（每条含任务书 §三 要求的八项字段）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_ISSUE_LOG.md`
- 构建 commit：`26677fd`
- SHA-256：`ea0c905bdcdeddd011cfa8a759488bd0fcd88729127dc1dcbb0ef2f3e3584105`
- 大小：37522 B（36.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `clean-env-test-record` — 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED）

- 构建方式：`python scripts/clean_env_check.py`
- 路径：`docs/V07_2_CLEAN_ENV_TEST.md`
- 构建 commit：`26677fd`
- SHA-256：`e862f3e7f7ea5b9f45a3aac1303ec9f13fb0d422f9760b4fbd67fd876d6831fc`
- 大小：2449 B（2.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `real-data-validation-plan` — 真实数据验证计划（明确标注为计划，尚未执行）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_REAL_DATA_VALIDATION_PLAN.md`
- 构建 commit：`26677fd`
- SHA-256：`226e588b50068abd8bebe004d114b5691e36da48411ce6a476167fc8b32e37fd`
- 大小：5914 B（5.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

