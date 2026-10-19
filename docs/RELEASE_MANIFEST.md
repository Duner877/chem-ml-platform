# Chem ML Platform v0.7.3 — Release Manifest

- **codename**: Trusted Delivery Release
- **commit**: `01099b8`
- **python**: 3.13.14
- **generated**: 2026-10-19T06:43:27+00:00
- **declared / built / tested / published**: 21 / 21 / 21 / 0

> `published` 仅在本机向发布渠道实际上传后才为真。本清单由本地构建生成，因此除已明确标注者外，全部产物均为**已构建、未发布**。

| 产物 | 类型 | 状态 | 大小 | SHA-256 | 文件 |
| --- | --- | --- | --- | --- | --- |
| 源码归档（可直接 push 到 GitHub 的完整源码树） | 源码归档 | 已构建 · 已测试 | 1564 KiB | `d2f513955f73d2f5…` | `C:/Users/hanku/Desktop/0.5 - 副本/01-源码/Chem-ML-Platform-v0.7.3.zip` |
| Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针） | 安装包 | 已构建 · 已测试 | 77333 KiB | `ecb371f8ebf7249e…` | `desktop/dist/Chem ML Platform Setup 0.7.3.exe` |
| NSIS 差分更新块映射（由 electron-builder 同步产出） | 安装包 | 已构建 · 已测试 | 82 KiB | `fcf9daa1b4e4777a…` | `desktop/dist/Chem ML Platform Setup 0.7.3.exe.blockmap` |
| 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单 | SBOM | 已构建 · 已测试 | 110 KiB | `873facbcae068c62…` | `sbom.json` |
| 质量门禁机器可读结果（逐步骤证据、退出码、日志路径） | 报告 | 已构建 · 已测试 | 14 KiB | `af84903177beaf69…` | `output/quality_gate.json` |
| 质量门禁人工可读报告 | 报告 | 已构建 · 已测试 | 11 KiB | `c8bdc96742bec8e2…` | `output/quality_gate.md` |
| 12 阶段 CI 流水线结果（每阶段独立退出码） | 报告 | 已构建 · 已测试 | 14 KiB | `0b514aa13b934437…` | `output/ci_pipeline.json` |
| 第三方许可证清单（由真实依赖元数据生成） | 合规 | 已构建 · 已测试 | 12 KiB | `4cf497f2fa4eef56…` | `docs/THIRD_PARTY_LICENSES.md` |
| 源码/依赖/数据集/模型来源与许可记录 | 合规 | 已构建 · 已测试 | 14 KiB | `6dfaa4c6a103be6c…` | `docs/PROVENANCE.md` |
| 根 NOTICE（分发组件归属声明） | 合规 | 已构建 · 已测试 | 8 KiB | `fd01f89f24c04636…` | `NOTICE` |
| 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率） | 报告 | 已构建 · 已测试 | 9 KiB | `3658df1be7b08e40…` | `docs/V07_2_SYNTHETIC_BENCHMARK.md` |
| 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据） | 报告 | 已构建 · 已测试 | 17 KiB | `5198cf7250ef329e…` | `docs/node-catalog.md` |
| Python 依赖锁定文件（含可复现安装所需的精确版本） | 运行时依赖 | 已构建 · 已测试 | 1 KiB | `7f010d168c157323…` | `requirements.lock` |
| 前端依赖锁文件（npm ci 使用的确定性依赖图） | 运行时依赖 | 已构建 · 已测试 | 46 KiB | `6f98177d4ad9646e…` | `frontend/package-lock.json` |
| 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包） | 开发环境 | 已构建 · 已测试 | 21 KiB | `347091c24dcdd022…` | `desktop/src/runtime-probe.js` |
| 结果复现验证报告（逐节点输出摘要，重复运行比对） | 报告 | 已构建 · 已测试 | 2 KiB | `eee3b99795036958…` | `output/reproducibility.json` |
| 插件与外部程序执行边界规范（P1-03 / P2-04） | 合规 | 已构建 · 已测试 | 10 KiB | `2868c3e7787562c2…` | `docs/V07_2_PLUGIN_SPEC.md` |
| v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录） | 报告 | 已构建 · 已测试 | 37 KiB | `133832427ec333ea…` | `docs/V07_2_RELEASE_REPORT.md` |
| 问题记录表（每条含任务书 §三 要求的八项字段） | 合规 | 已构建 · 已测试 | 37 KiB | `ea0c905bdcdeddd0…` | `docs/V07_2_ISSUE_LOG.md` |
| 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED） | 报告 | 已构建 · 已测试 | 2 KiB | `89b7b543cf1d305d…` | `docs/V07_2_CLEAN_ENV_TEST.md` |
| 真实数据验证计划（明确标注为计划，尚未执行） | 报告 | 已构建 · 已测试 | 6 KiB | `226e588b50068abd…` | `docs/V07_2_REAL_DATA_VALIDATION_PLAN.md` |

## 逐项明细

### `source-archive` — 源码归档（可直接 push 到 GitHub 的完整源码树）

- 构建方式：`python scripts/package.py --name Chem-ML-Platform-v{version} --output ../Chem-ML-Platform-v{version}.zip`
- 路径：`C:/Users/hanku/Desktop/0.5 - 副本/01-源码/Chem-ML-Platform-v0.7.3.zip`
- 构建 commit：`01099b8`
- SHA-256：`d2f513955f73d2f5d3cdf172c25be18c6c86b55522e03ce7b77ed08239784a7c`
- 大小：1601445 B（1563.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/RELEASE_MANIFEST.md, SHA256SUMS
- 发布说明：未从本机上传到任何发布渠道

### `windows-installer` — Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针）

- 构建方式：`cd desktop && npm install && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.3.exe`
- 构建 commit：`01099b8`
- SHA-256：`ecb371f8ebf7249ec4b0d68225122b0b7e84ad9dfd3b70e68f69bdb65c982a0b`
- 大小：79188768 B（77332.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/V07_2_CLEAN_ENV_TEST.md
- 发布说明：未从本机上传到任何发布渠道

### `installer-blockmap` — NSIS 差分更新块映射（由 electron-builder 同步产出）

- 构建方式：`cd desktop && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.3.exe.blockmap`
- 构建 commit：`01099b8`
- SHA-256：`fcf9daa1b4e4777a3afbdc321cbf7c2eadf30f4bf3f5a5e3f086428a385de001`
- 大小：83829 B（81.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `sbom` — 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单

- 构建方式：`python scripts/license_report.py --write`
- 路径：`sbom.json`
- 构建 commit：`01099b8`
- SHA-256：`873facbcae068c622e18de61fe2c677dd26a26c5515f1969686969185be8e24e`
- 大小：112800 B（110.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/THIRD_PARTY_LICENSES.md
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-json` — 质量门禁机器可读结果（逐步骤证据、退出码、日志路径）

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.json`
- 构建 commit：`01099b8`
- SHA-256：`af84903177beaf69e37e25b8f3345f825c68bfdaaa457186cbce66eda5c571f1`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：14292 B（14.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-md` — 质量门禁人工可读报告

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.md`
- 构建 commit：`01099b8`
- SHA-256：`c8bdc96742bec8e2cf690b461d298c5e4db5e8b68faf949ff8cd96a5bfc55612`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：11131 B（10.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `ci-pipeline-json` — 12 阶段 CI 流水线结果（每阶段独立退出码）

- 构建方式：`python scripts/ci_pipeline.py`
- 路径：`output/ci_pipeline.json`
- 构建 commit：`01099b8`
- SHA-256：`0b514aa13b9344372956106121e28489aed86a2f0dcda01c583f882d553cce53`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：14605 B（14.3 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `third-party-licences` — 第三方许可证清单（由真实依赖元数据生成）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`docs/THIRD_PARTY_LICENSES.md`
- 构建 commit：`01099b8`
- SHA-256：`4cf497f2fa4eef56a07f907bbedd129cbc4f856114803baf020c8dfa1e73b35a`
- 大小：12761 B（12.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `provenance-record` — 源码/依赖/数据集/模型来源与许可记录

- 构建方式：`(maintained by hand; see docs/PROVENANCE.md)`
- 路径：`docs/PROVENANCE.md`
- 构建 commit：`01099b8`
- SHA-256：`6dfaa4c6a103be6cbeb89d0758d804d18ca8414eb3f94270f1532820041e4ccf`
- 大小：13881 B（13.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `notice` — 根 NOTICE（分发组件归属声明）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`NOTICE`
- 构建 commit：`01099b8`
- SHA-256：`fd01f89f24c04636914608d4786b1069b11d246158c65228da6dfe42accd2928`
- 大小：7720 B（7.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `synthetic-benchmark-report` — 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率）

- 构建方式：`python scripts/benchmark_lcms.py`
- 路径：`docs/V07_2_SYNTHETIC_BENCHMARK.md`
- 构建 commit：`01099b8`
- SHA-256：`3658df1be7b08e403dfe8237d03b4c5b6a33be0b2983d242dacf07b329718661`
- 大小：8813 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/benchmark_lcms.json
- 发布说明：未从本机上传到任何发布渠道

### `node-capability-catalogue` — 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据）

- 构建方式：`python scripts/node_catalog.py --write`
- 路径：`docs/node-catalog.md`
- 构建 commit：`01099b8`
- SHA-256：`5198cf7250ef329e10adc8b200912deae6b43d8f8b641a73a469ff63fdf0fe80`
- 大小：16981 B（16.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `python-dependency-lock` — Python 依赖锁定文件（含可复现安装所需的精确版本）

- 构建方式：`pip install -r requirements.txt && pip freeze (see docs/V07_2_DEPENDENCIES.md)`
- 路径：`requirements.lock`
- 构建 commit：`01099b8`
- SHA-256：`7f010d168c157323eed364bb5c005aab1c8bb7e846e675ddfc3f2a8a6da40da6`
- 大小：1526 B（1.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `frontend-dependency-lock` — 前端依赖锁文件（npm ci 使用的确定性依赖图）

- 构建方式：`npm install (committed lockfile)`
- 路径：`frontend/package-lock.json`
- 构建 commit：`01099b8`
- SHA-256：`6f98177d4ad9646e483c75de26f65026e9effab18d4199837e3e40bd237a0ec4`
- 大小：47329 B（46.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `desktop-runtime-probe` — 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包）

- 构建方式：`(first-party source)`
- 路径：`desktop/src/runtime-probe.js`
- 构建 commit：`01099b8`
- SHA-256：`347091c24dcdd022305d905a3339c39001dd57f13838f04630558dac6ce774e6`
- 大小：21712 B（21.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_desktop_runtime.py
- 发布说明：未从本机上传到任何发布渠道

### `reproducibility-report` — 结果复现验证报告（逐节点输出摘要，重复运行比对）

- 构建方式：`python scripts/verify_reproducibility.py --repeat 2`
- 路径：`output/reproducibility.json`
- 构建 commit：`01099b8`
- SHA-256：`eee3b99795036958eb808209649d24c8fe8ff0f61d21995de5771e49b69cd7e5`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：2026 B（2.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_provenance_reproducibility.py
- 发布说明：未从本机上传到任何发布渠道

### `plugin-spec` — 插件与外部程序执行边界规范（P1-03 / P2-04）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_PLUGIN_SPEC.md`
- 构建 commit：`01099b8`
- SHA-256：`2868c3e7787562c2b8c377d289fa341e6625fd6f4dd1bcd9fd2e9379812afd7a`
- 大小：10003 B（9.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_1_capabilities.py
- 发布说明：未从本机上传到任何发布渠道

### `release-report` — v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录）

- 构建方式：`(maintained by hand; numbers quoted from output/quality_gate.json)`
- 路径：`docs/V07_2_RELEASE_REPORT.md`
- 构建 commit：`01099b8`
- SHA-256：`133832427ec333eac049109264a49a352f34d7484128bc003329e87ad117da98`
- 大小：38124 B（37.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/quality_gate.json
- 发布说明：未从本机上传到任何发布渠道

### `issue-log` — 问题记录表（每条含任务书 §三 要求的八项字段）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_ISSUE_LOG.md`
- 构建 commit：`01099b8`
- SHA-256：`ea0c905bdcdeddd011cfa8a759488bd0fcd88729127dc1dcbb0ef2f3e3584105`
- 大小：37522 B（36.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `clean-env-test-record` — 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED）

- 构建方式：`python scripts/clean_env_check.py`
- 路径：`docs/V07_2_CLEAN_ENV_TEST.md`
- 构建 commit：`01099b8`
- SHA-256：`89b7b543cf1d305d86842b01c7b3dba77aa761690c7a3e646385db6a43303d5f`
- 大小：2488 B（2.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `real-data-validation-plan` — 真实数据验证计划（明确标注为计划，尚未执行）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_REAL_DATA_VALIDATION_PLAN.md`
- 构建 commit：`01099b8`
- SHA-256：`226e588b50068abd8bebe004d114b5691e36da48411ce6a476167fc8b32e37fd`
- 大小：5914 B（5.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

