# Chem ML Platform v0.7.4 — Release Manifest

- **codename**: Trusted Delivery Release
- **commit**: `6d30a0f`
- **python**: 3.13.14
- **generated**: 2026-10-27T08:29:06+00:00
- **declared / built / tested / published**: 21 / 20 / 19 / 0

> `published` 仅在本机向发布渠道实际上传后才为真。本清单由本地构建生成，因此除已明确标注者外，全部产物均为**已构建、未发布**。

| 产物 | 类型 | 状态 | 大小 | SHA-256 | 文件 |
| --- | --- | --- | --- | --- | --- |
| 源码归档（可直接 push 到 GitHub 的完整源码树） | 源码归档 | 已构建 · 已测试 | 2005 KiB | `3c9d294f9baebd57…` | `C:/Users/hanku/Desktop/Chem ML Platform/01-源码/Chem-ML-Platform-v0.7.4.zip` |
| Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针） | 安装包 | 已构建 · 已测试 | 77371 KiB | `434fdfe72f7bbe73…` | `desktop/dist/Chem ML Platform Setup 0.7.4.exe` |
| NSIS 差分更新块映射（由 electron-builder 同步产出） | 安装包 | 已构建 · 已测试 | 82 KiB | `0ea2c59289c4d29e…` | `desktop/dist/Chem ML Platform Setup 0.7.4.exe.blockmap` |
| 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单 | SBOM | 已构建 · 已测试 | 105 KiB | `fa90a7e100d81572…` | `sbom.json` |
| 质量门禁机器可读结果（逐步骤证据、退出码、日志路径） | 报告 | 已构建 · 已测试 | 14 KiB | `6bdeb349c00dbb1e…` | `output/quality_gate.json` |
| 质量门禁人工可读报告 | 报告 | 已构建 · 已测试 | 11 KiB | `553a79cf670ea3d4…` | `output/quality_gate.md` |
| 12 阶段 CI 流水线结果（每阶段独立退出码） | 报告 | 未构建 | — | `—` | `（缺失）` |
| 第三方许可证清单（由真实依赖元数据生成） | 合规 | 已构建 · 已测试 | 13 KiB | `a126a50c444aea6c…` | `docs/THIRD_PARTY_LICENSES.md` |
| 源码/依赖/数据集/模型来源与许可记录 | 合规 | 已构建 · 已测试 | 14 KiB | `5a68349bc041c71c…` | `docs/PROVENANCE.md` |
| 根 NOTICE（分发组件归属声明） | 合规 | 已构建 · 已测试 | 9 KiB | `ca796bca8c0c5984…` | `NOTICE` |
| 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率） | 报告 | 已构建 · 未测试 | 9 KiB | `3658df1be7b08e40…` | `docs/V07_2_SYNTHETIC_BENCHMARK.md` |
| 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据） | 报告 | 已构建 · 已测试 | 16 KiB | `6f0ed1944e530701…` | `docs/node-catalog.md` |
| Python 依赖锁定文件（含可复现安装所需的精确版本） | 运行时依赖 | 已构建 · 已测试 | 1 KiB | `7f8862a24cd3acc3…` | `requirements.lock` |
| 前端依赖锁文件（npm ci 使用的确定性依赖图） | 运行时依赖 | 已构建 · 已测试 | 44 KiB | `abf8189cc012b05c…` | `frontend/package-lock.json` |
| 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包） | 开发环境 | 已构建 · 已测试 | 21 KiB | `347091c24dcdd022…` | `desktop/src/runtime-probe.js` |
| 结果复现验证报告（逐节点输出摘要，重复运行比对） | 报告 | 已构建 · 已测试 | 2 KiB | `d6fc3f86ff19cfdf…` | `output/reproducibility.json` |
| 插件与外部程序执行边界规范（P1-03 / P2-04） | 合规 | 已构建 · 已测试 | 10 KiB | `2868c3e7787562c2…` | `docs/V07_2_PLUGIN_SPEC.md` |
| v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录） | 报告 | 已构建 · 已测试 | 37 KiB | `0b84bfa610efcc25…` | `docs/V07_2_RELEASE_REPORT.md` |
| 问题记录表（每条含任务书 §三 要求的八项字段） | 合规 | 已构建 · 已测试 | 37 KiB | `ea0c905bdcdeddd0…` | `docs/V07_2_ISSUE_LOG.md` |
| 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED） | 报告 | 已构建 · 已测试 | 2 KiB | `e862f3e7f7ea5b9f…` | `docs/V07_2_CLEAN_ENV_TEST.md` |
| 真实数据验证计划（明确标注为计划，尚未执行） | 报告 | 已构建 · 已测试 | 6 KiB | `226e588b50068abd…` | `docs/V07_2_REAL_DATA_VALIDATION_PLAN.md` |

## 逐项明细

### `source-archive` — 源码归档（可直接 push 到 GitHub 的完整源码树）

- 构建方式：`python scripts/package.py --name Chem-ML-Platform-v{version} --output ../Chem-ML-Platform-v{version}.zip`
- 路径：`C:/Users/hanku/Desktop/Chem ML Platform/01-源码/Chem-ML-Platform-v0.7.4.zip`
- 构建 commit：`6d30a0f`
- SHA-256：`3c9d294f9baebd5780262bed7d11f62fc0ed088a621154985823453c54bf649a`
- 大小：2053471 B（2005.3 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/RELEASE_MANIFEST.md, SHA256SUMS
- 发布说明：未从本机上传到任何发布渠道

### `windows-installer` — Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针）

- 构建方式：`cd desktop && npm install && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.4.exe`
- 构建 commit：`6d30a0f`
- SHA-256：`434fdfe72f7bbe736c3da9cbb56018845cdc84484650ae8ace70c2fc4a2d4190`
- 大小：79228074 B（77371.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/V07_2_CLEAN_ENV_TEST.md
- 发布说明：未从本机上传到任何发布渠道

### `installer-blockmap` — NSIS 差分更新块映射（由 electron-builder 同步产出）

- 构建方式：`cd desktop && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.4.exe.blockmap`
- 构建 commit：`6d30a0f`
- SHA-256：`0ea2c59289c4d29ea5ae0759b46df163fbf90db7bb9ee7fba8823d5b4f75ce2c`
- 大小：83696 B（81.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `sbom` — 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单

- 构建方式：`python scripts/license_report.py --write`
- 路径：`sbom.json`
- 构建 commit：`6d30a0f`
- SHA-256：`fa90a7e100d81572e7b405c021baf670a8945852255f1b0ae813a9a5c4b06536`
- 大小：107466 B（104.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/THIRD_PARTY_LICENSES.md
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-json` — 质量门禁机器可读结果（逐步骤证据、退出码、日志路径）

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.json`
- 构建 commit：`6d30a0f`
- SHA-256：`6bdeb349c00dbb1e3a5977c92baf99267785700bac6da0dec4fb15eb5d64c5b8`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：14286 B（14.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-md` — 质量门禁人工可读报告

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.md`
- 构建 commit：`6d30a0f`
- SHA-256：`553a79cf670ea3d494e4a965f3c2bcabd20a9c953a6d872c58674d1cd9d1adca`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：11124 B（10.9 KiB）
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
- 构建 commit：`6d30a0f`
- SHA-256：`a126a50c444aea6c437a9409f6df1200f7b96cc098f79bddc964085f2c2b082f`
- 大小：13714 B（13.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `provenance-record` — 源码/依赖/数据集/模型来源与许可记录

- 构建方式：`(maintained by hand; see docs/PROVENANCE.md)`
- 路径：`docs/PROVENANCE.md`
- 构建 commit：`6d30a0f`
- SHA-256：`5a68349bc041c71c120a0c62a82bcf9be2c41c03b228c5cdbd5c9a26607f47d1`
- 大小：13860 B（13.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `notice` — 根 NOTICE（分发组件归属声明）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`NOTICE`
- 构建 commit：`6d30a0f`
- SHA-256：`ca796bca8c0c5984de316d0f99aa96ca0ee48308df9708bbaa46c0aac3204b3c`
- 大小：8855 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `synthetic-benchmark-report` — 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率）

- 构建方式：`python scripts/benchmark_lcms.py`
- 路径：`docs/V07_2_SYNTHETIC_BENCHMARK.md`
- 构建 commit：`6d30a0f`
- SHA-256：`3658df1be7b08e403dfe8237d03b4c5b6a33be0b2983d242dacf07b329718661`
- 大小：8813 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 否 / 否
- 测试说明：缺少证据文件: output/benchmark_lcms.json
- 发布说明：未从本机上传到任何发布渠道

### `node-capability-catalogue` — 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据）

- 构建方式：`python scripts/node_catalog.py --write`
- 路径：`docs/node-catalog.md`
- 构建 commit：`6d30a0f`
- SHA-256：`6f0ed1944e5307019f70e66a772f6f14d0e1dbab58c887ea780a160b355ae2df`
- 大小：16784 B（16.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `python-dependency-lock` — Python 依赖锁定文件（含可复现安装所需的精确版本）

- 构建方式：`pip install -r requirements.txt && pip freeze (see docs/V07_2_DEPENDENCIES.md)`
- 路径：`requirements.lock`
- 构建 commit：`6d30a0f`
- SHA-256：`7f8862a24cd3acc351000cc0f269140acb58fcd247d8f1eb28ab902e0979e6b3`
- 大小：1474 B（1.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `frontend-dependency-lock` — 前端依赖锁文件（npm ci 使用的确定性依赖图）

- 构建方式：`npm install (committed lockfile)`
- 路径：`frontend/package-lock.json`
- 构建 commit：`6d30a0f`
- SHA-256：`abf8189cc012b05cbb50b5bd1f0878d4e2821b684a3bdfc900ce1a1dc411f483`
- 大小：45443 B（44.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `desktop-runtime-probe` — 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包）

- 构建方式：`(first-party source)`
- 路径：`desktop/src/runtime-probe.js`
- 构建 commit：`6d30a0f`
- SHA-256：`347091c24dcdd022305d905a3339c39001dd57f13838f04630558dac6ce774e6`
- 大小：21712 B（21.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_desktop_runtime.py
- 发布说明：未从本机上传到任何发布渠道

### `reproducibility-report` — 结果复现验证报告（逐节点输出摘要，重复运行比对）

- 构建方式：`python scripts/verify_reproducibility.py --repeat 2`
- 路径：`output/reproducibility.json`
- 构建 commit：`6d30a0f`
- SHA-256：`d6fc3f86ff19cfdfc0f109a0b8512f20d89322cf37078d56ba399ba906204b9f`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：2026 B（2.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_provenance_reproducibility.py
- 发布说明：未从本机上传到任何发布渠道

### `plugin-spec` — 插件与外部程序执行边界规范（P1-03 / P2-04）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_PLUGIN_SPEC.md`
- 构建 commit：`6d30a0f`
- SHA-256：`2868c3e7787562c2b8c377d289fa341e6625fd6f4dd1bcd9fd2e9379812afd7a`
- 大小：10003 B（9.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_1_capabilities.py
- 发布说明：未从本机上传到任何发布渠道

### `release-report` — v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录）

- 构建方式：`(maintained by hand; numbers quoted from output/quality_gate.json)`
- 路径：`docs/V07_2_RELEASE_REPORT.md`
- 构建 commit：`6d30a0f`
- SHA-256：`0b84bfa610efcc25f901467c5aaa5b050b1a083b8e8bb4c4327013ad81b1537c`
- 大小：37630 B（36.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/quality_gate.json
- 发布说明：未从本机上传到任何发布渠道

### `issue-log` — 问题记录表（每条含任务书 §三 要求的八项字段）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_ISSUE_LOG.md`
- 构建 commit：`6d30a0f`
- SHA-256：`ea0c905bdcdeddd011cfa8a759488bd0fcd88729127dc1dcbb0ef2f3e3584105`
- 大小：37522 B（36.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `clean-env-test-record` — 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED）

- 构建方式：`python scripts/clean_env_check.py`
- 路径：`docs/V07_2_CLEAN_ENV_TEST.md`
- 构建 commit：`6d30a0f`
- SHA-256：`e862f3e7f7ea5b9f45a3aac1303ec9f13fb0d422f9760b4fbd67fd876d6831fc`
- 大小：2449 B（2.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `real-data-validation-plan` — 真实数据验证计划（明确标注为计划，尚未执行）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_REAL_DATA_VALIDATION_PLAN.md`
- 构建 commit：`6d30a0f`
- SHA-256：`226e588b50068abd8bebe004d114b5691e36da48411ce6a476167fc8b32e37fd`
- 大小：5914 B（5.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

