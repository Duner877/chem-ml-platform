# Chem ML Platform v0.7.2 — Release Manifest

- **codename**: Trusted Delivery Release
- **commit**: `fd5503d`
- **python**: 3.13.14
- **generated**: 2026-10-14T13:22:34+00:00
- **declared / built / tested / published**: 21 / 21 / 21 / 0

> `published` 仅在本机向发布渠道实际上传后才为真。本清单由本地构建生成，因此除已明确标注者外，全部产物均为**已构建、未发布**。

| 产物 | 类型 | 状态 | 大小 | SHA-256 | 文件 |
| --- | --- | --- | --- | --- | --- |
| 源码归档（可直接 push 到 GitHub 的完整源码树） | 源码归档 | 已构建 · 已测试 | 1097 KiB | `7b6c0751a0d09f99…` | `C:/Users/hanku/Desktop/0.5 - 副本/Chem-ML-Platform-v0.7.2.zip` |
| Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针） | 安装包 | 已构建 · 已测试 | 77112 KiB | `e556cec96689f438…` | `desktop/dist/Chem ML Platform Setup 0.7.2.exe` |
| NSIS 差分更新块映射（由 electron-builder 同步产出） | 安装包 | 已构建 · 已测试 | 82 KiB | `fc5ae79deeb20019…` | `desktop/dist/Chem ML Platform Setup 0.7.2.exe.blockmap` |
| 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单 | SBOM | 已构建 · 已测试 | 108 KiB | `b37d4658f88cf10b…` | `sbom.json` |
| 质量门禁机器可读结果（逐步骤证据、退出码、日志路径） | 报告 | 已构建 · 已测试 | 14 KiB | `3fcd1325e8aaa173…` | `output/quality_gate.json` |
| 质量门禁人工可读报告 | 报告 | 已构建 · 已测试 | 11 KiB | `89bd243f6da7242d…` | `output/quality_gate.md` |
| 12 阶段 CI 流水线结果（每阶段独立退出码） | 报告 | 已构建 · 已测试 | 2 KiB | `4fd8cd954c2845d4…` | `output/ci_pipeline.json` |
| 第三方许可证清单（由真实依赖元数据生成） | 合规 | 已构建 · 已测试 | 12 KiB | `e7a0d017ef2a4820…` | `docs/THIRD_PARTY_LICENSES.md` |
| 源码/依赖/数据集/模型来源与许可记录 | 合规 | 已构建 · 已测试 | 11 KiB | `eb551da2c6832034…` | `docs/PROVENANCE.md` |
| 根 NOTICE（分发组件归属声明） | 合规 | 已构建 · 已测试 | 7 KiB | `4371c042f414de29…` | `NOTICE` |
| 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率） | 报告 | 已构建 · 已测试 | 9 KiB | `3658df1be7b08e40…` | `docs/V07_2_SYNTHETIC_BENCHMARK.md` |
| 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据） | 报告 | 已构建 · 已测试 | 14 KiB | `c5e6fd3edbdb3928…` | `docs/node-catalog.md` |
| Python 依赖锁定文件（含可复现安装所需的精确版本） | 运行时依赖 | 已构建 · 已测试 | 1 KiB | `7f010d168c157323…` | `requirements.lock` |
| 前端依赖锁文件（npm ci 使用的确定性依赖图） | 运行时依赖 | 已构建 · 已测试 | 46 KiB | `a640cde957d121f9…` | `frontend/package-lock.json` |
| 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包） | 开发环境 | 已构建 · 已测试 | 21 KiB | `347091c24dcdd022…` | `desktop/src/runtime-probe.js` |
| 结果复现验证报告（逐节点输出摘要，重复运行比对） | 报告 | 已构建 · 已测试 | 2 KiB | `da673516abbb428c…` | `output/reproducibility.json` |
| 插件与外部程序执行边界规范（P1-03 / P2-04） | 合规 | 已构建 · 已测试 | 10 KiB | `2868c3e7787562c2…` | `docs/V07_2_PLUGIN_SPEC.md` |
| v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录） | 报告 | 已构建 · 已测试 | 31 KiB | `d4258e5766f6da02…` | `docs/V07_2_RELEASE_REPORT.md` |
| 问题记录表（每条含任务书 §三 要求的八项字段） | 合规 | 已构建 · 已测试 | 22 KiB | `c7785d1c5605b228…` | `docs/V07_2_ISSUE_LOG.md` |
| 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED） | 报告 | 已构建 · 已测试 | 2 KiB | `a5fd18f450c52654…` | `docs/V07_2_CLEAN_ENV_TEST.md` |
| 真实数据验证计划（明确标注为计划，尚未执行） | 报告 | 已构建 · 已测试 | 6 KiB | `226e588b50068abd…` | `docs/V07_2_REAL_DATA_VALIDATION_PLAN.md` |

## 逐项明细

### `source-archive` — 源码归档（可直接 push 到 GitHub 的完整源码树）

- 构建方式：`python scripts/package.py --name Chem-ML-Platform-v{version} --output ../Chem-ML-Platform-v{version}.zip`
- 路径：`C:/Users/hanku/Desktop/0.5 - 副本/Chem-ML-Platform-v0.7.2.zip`
- 构建 commit：`fd5503d`
- SHA-256：`7b6c0751a0d09f99041d072f8ee766caa33280306554b00ac193b8008c237f2a`
- 大小：1123543 B（1097.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/RELEASE_MANIFEST.md, SHA256SUMS
- 发布说明：未从本机上传到任何发布渠道

### `windows-installer` — Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针）

- 构建方式：`cd desktop && npm install && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.2.exe`
- 构建 commit：`fd5503d`
- SHA-256：`e556cec96689f4389237f53f69183c94a2e3c8da0ad190da072b9eb15de50f9c`
- 大小：78963083 B（77112.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/V07_2_CLEAN_ENV_TEST.md
- 发布说明：未从本机上传到任何发布渠道

### `installer-blockmap` — NSIS 差分更新块映射（由 electron-builder 同步产出）

- 构建方式：`cd desktop && npm run build`
- 路径：`desktop/dist/Chem ML Platform Setup 0.7.2.exe.blockmap`
- 构建 commit：`fd5503d`
- SHA-256：`fc5ae79deeb20019a26b5f0584814e9de776595e7ead51a0756db6c8ebc04054`
- 大小：83462 B（81.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `sbom` — 与实际构建依赖对应的 CycloneDX 1.5 软件物料清单

- 构建方式：`python scripts/license_report.py --write`
- 路径：`sbom.json`
- 构建 commit：`fd5503d`
- SHA-256：`b37d4658f88cf10b20281765a161cb6781aca732887f50a4b9af392469a5e975`
- 大小：110505 B（107.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: docs/THIRD_PARTY_LICENSES.md
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-json` — 质量门禁机器可读结果（逐步骤证据、退出码、日志路径）

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.json`
- 构建 commit：`fd5503d`
- SHA-256：`3fcd1325e8aaa17312de6469a256757d72b88ced026d7816f83ec25e925cd092`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：14183 B（13.9 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `quality-gate-md` — 质量门禁人工可读报告

- 构建方式：`python scripts/quality_gate.py`
- 路径：`output/quality_gate.md`
- 构建 commit：`fd5503d`
- SHA-256：`89bd243f6da7242dade2b0494e895c27e9010b9c2c3662496148c593ea29c537`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：10961 B（10.7 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `ci-pipeline-json` — 12 阶段 CI 流水线结果（每阶段独立退出码）

- 构建方式：`python scripts/ci_pipeline.py`
- 路径：`output/ci_pipeline.json`
- 构建 commit：`fd5503d`
- SHA-256：`4fd8cd954c2845d49333e001cfaec324fa377de751b540afd674b6c146ae4d77`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：2181 B（2.1 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `third-party-licences` — 第三方许可证清单（由真实依赖元数据生成）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`docs/THIRD_PARTY_LICENSES.md`
- 构建 commit：`fd5503d`
- SHA-256：`e7a0d017ef2a4820eb2dbe676293a153c3bc2a7ed3ca016dbc717068b28c23fe`
- 大小：12404 B（12.1 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `provenance-record` — 源码/依赖/数据集/模型来源与许可记录

- 构建方式：`(maintained by hand; see docs/PROVENANCE.md)`
- 路径：`docs/PROVENANCE.md`
- 构建 commit：`fd5503d`
- SHA-256：`eb551da2c6832034ecc937558adb8801d61b8b24715fe128f4193ab08ccb5c75`
- 大小：11682 B（11.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `notice` — 根 NOTICE（分发组件归属声明）

- 构建方式：`python scripts/license_report.py --write`
- 路径：`NOTICE`
- 构建 commit：`fd5503d`
- SHA-256：`4371c042f414de29903351ef979f063f934928afbe7d400392692e799d825f04`
- 大小：7667 B（7.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `synthetic-benchmark-report` — 合成基准报告（明确标注为 synthetic，不代表真实仪器准确率）

- 构建方式：`python scripts/benchmark_lcms.py`
- 路径：`docs/V07_2_SYNTHETIC_BENCHMARK.md`
- 构建 commit：`fd5503d`
- SHA-256：`3658df1be7b08e403dfe8237d03b4c5b6a33be0b2983d242dacf07b329718661`
- 大小：8813 B（8.6 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/benchmark_lcms.json
- 发布说明：未从本机上传到任何发布渠道

### `node-capability-catalogue` — 节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据）

- 构建方式：`python scripts/node_catalog.py --write`
- 路径：`docs/node-catalog.md`
- 构建 commit：`fd5503d`
- SHA-256：`c5e6fd3edbdb3928074a8168deeeeb0b38dcbfc1b60cbe52593a5d20b37841c2`
- 大小：14772 B（14.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `python-dependency-lock` — Python 依赖锁定文件（含可复现安装所需的精确版本）

- 构建方式：`pip install -r requirements.txt && pip freeze (see docs/V07_2_DEPENDENCIES.md)`
- 路径：`requirements.lock`
- 构建 commit：`fd5503d`
- SHA-256：`7f010d168c157323eed364bb5c005aab1c8bb7e846e675ddfc3f2a8a6da40da6`
- 大小：1526 B（1.5 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `frontend-dependency-lock` — 前端依赖锁文件（npm ci 使用的确定性依赖图）

- 构建方式：`npm install (committed lockfile)`
- 路径：`frontend/package-lock.json`
- 构建 commit：`fd5503d`
- SHA-256：`a640cde957d121f9bde72cf3070fcfca3c8c23b34443221528cfdce901790ade`
- 大小：47329 B（46.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `desktop-runtime-probe` — 桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包）

- 构建方式：`(first-party source)`
- 路径：`desktop/src/runtime-probe.js`
- 构建 commit：`fd5503d`
- SHA-256：`347091c24dcdd022305d905a3339c39001dd57f13838f04630558dac6ce774e6`
- 大小：21712 B（21.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_desktop_runtime.py
- 发布说明：未从本机上传到任何发布渠道

### `reproducibility-report` — 结果复现验证报告（逐节点输出摘要，重复运行比对）

- 构建方式：`python scripts/verify_reproducibility.py --repeat 2`
- 路径：`output/reproducibility.json`
- 构建 commit：`fd5503d`
- SHA-256：`da673516abbb428c318ee9933e8808143f29ae3280555b2b1f15ca0a33cacff3`
- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），因此校验时按「存在性」比对，不锁定摘要。
- 大小：2026 B（2.0 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_2_provenance_reproducibility.py
- 发布说明：未从本机上传到任何发布渠道

### `plugin-spec` — 插件与外部程序执行边界规范（P1-03 / P2-04）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_PLUGIN_SPEC.md`
- 构建 commit：`fd5503d`
- SHA-256：`2868c3e7787562c2b8c377d289fa341e6625fd6f4dd1bcd9fd2e9379812afd7a`
- 大小：10003 B（9.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: tests/test_v07_1_capabilities.py
- 发布说明：未从本机上传到任何发布渠道

### `release-report` — v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录）

- 构建方式：`(maintained by hand; numbers quoted from output/quality_gate.json)`
- 路径：`docs/V07_2_RELEASE_REPORT.md`
- 构建 commit：`fd5503d`
- SHA-256：`d4258e5766f6da0223d0cdf3a1f7e51e1cb6cee4015c8caacd1bcb6f114b88c5`
- 大小：31902 B（31.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：证据齐备: output/quality_gate.json
- 发布说明：未从本机上传到任何发布渠道

### `issue-log` — 问题记录表（每条含任务书 §三 要求的八项字段）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_ISSUE_LOG.md`
- 构建 commit：`fd5503d`
- SHA-256：`c7785d1c5605b228bcf374d7d516fdd74bee4e273dade46e35a2db764fbf8531`
- 大小：22722 B（22.2 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `clean-env-test-record` — 干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED）

- 构建方式：`python scripts/clean_env_check.py`
- 路径：`docs/V07_2_CLEAN_ENV_TEST.md`
- 构建 commit：`fd5503d`
- SHA-256：`a5fd18f450c52654251a39d0a320ef620c0eb1cc1b0b5b97273708611d2d2aac`
- 大小：2422 B（2.4 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

### `real-data-validation-plan` — 真实数据验证计划（明确标注为计划，尚未执行）

- 构建方式：`(maintained by hand)`
- 路径：`docs/V07_2_REAL_DATA_VALIDATION_PLAN.md`
- 构建 commit：`fd5503d`
- SHA-256：`226e588b50068abd8bebe004d114b5691e36da48411ce6a476167fc8b32e37fd`
- 大小：5914 B（5.8 KiB）
- 构建 / 测试 / 发布：是 / 是 / 否
- 测试说明：无独立测试证据要求
- 发布说明：未从本机上传到任何发布渠道

