# 版本管理规范（v0.7.2 / 任务 P0-04）

> **一句话**：版本号只允许出现在一个地方。其他所有位置都是**派生**的，并且必须能被
> `python scripts/version.py --check` 证明仍然一致。

---

## 1. 唯一版本来源

`chemml_version.py`（仓库根）：

```python
__version__ = "0.7.2"                    # 产品版本，只在这里改
VERSION = __version__                    # 向后兼容别名
__codename__ = "Trusted Delivery Release"

git_commit(short=True) -> str            # 优先 CHEMML_BUILD_COMMIT，其次 git rev-parse
build_metadata() -> dict                 # version / codename / commit / built_at / python
```

`chemml_version.py` 不导入任何项目模块，因此任何层都能安全地读取它。

---

## 2. 派生位置清单

| 派生位置 | 派生方式 | 由谁保证 |
| --- | --- | --- |
| `backend/app.py` | `from chemml_version import VERSION` | `--check` 禁止硬编码字面量 |
| `node_registry/__init__.py` | 同上 | 同上 |
| `workflow_engine/__init__.py` | `try: from chemml_version import VERSION as __version__` | 同上 |
| `memory/__init__.py` | 同上 | 同上 |
| `node_sdk/python/chemml_sdk/__init__.py` | 同上（SDK 独立使用时回退字面量） | 同上 |
| `nodes/report.py` | 字面量，必须等于 `VERSION` | `PY_LITERAL_TARGETS` |
| `frontend`（浏览器包） | Vite `define: __CHEMML_VERSION__`，**构建时读 `chemml_version.py`** | 前端不再持有自己的版本字面量 |
| `frontend/package.json` | `--write` 回写，`--check` 校验 | JSON 目标 |
| `frontend/package-lock.json` | 同上（`version` 与 `packages[""].version`） | JSON 目标 |
| `desktop/package.json` | 同上（含 `description` 中的 v 前缀） | JSON 目标 + `DESCRIPTION_TARGETS` |
| `node_sdk/nodejs/package.json` | 同上 | JSON 目标 |
| `workflows/*.json` | `--write` 回写 `version` 字段 | 工作流目标 |
| `README.md` / `本地安装说明.md` / `requirements*.txt` 标题 | 人工修改 | `TEXT_TARGETS` |
| `node_sdk/python/README.md` | 人工修改 | `TEXT_TARGETS` |
| `CHANGELOG.md` | 人工新增 `## [0.7.2]` 段落 | `--check` 要求存在，且**最新段落**必须是当前版本 |
| `sbom.json` / `NOTICE` / `THIRD_PARTY_LICENSES.md` | `scripts/license_report.py --write` | 质量门禁阶段 |
| `docs/RELEASE_MANIFEST.*` / `SHA256SUMS` | `scripts/release_manifest.py` | 质量门禁阶段 |

---

## 3. 工具

```bash
python scripts/version.py --show     # 打印版本 + commit
python scripts/version.py --check    # 任一派生位置不一致 -> 退出码 1（逐条列出）
python scripts/version.py --write    # 回写可机器修改的产物（package.json / 工作流）
python scripts/version.py --check --json drift.json
```

`--check` 的输出是**逐条**的，指明是哪个文件、期望什么、实际是什么：

```
VERSION DRIFT: 0.7.2
  - desktop/package.json: advertises v0.7.1 != v0.7.2
  - CHANGELOG.md: newest section is 0.7.1, expected 0.7.2
```

质量门禁中对应阶段为 `version_consistency`（合规类，必需）。

---

## 4. Git tag 与产物命名

| 项目 | 规则 | 示例 |
| --- | --- | --- |
| 分支 | `main` | — |
| tag | `v<MAJOR>.<MINOR>.<PATCH>`，附注标签 | `v0.7.2` |
| 源码归档 | `Chem-ML-Platform-v<version>.zip` | `Chem-ML-Platform-v0.7.2.zip` |
| 安装包 | electron-builder 用 `productName` + `version` 生成 | `Chem ML Platform Setup 0.7.2.exe` |
| SBOM | `sbom.json`（仓库根） | — |
| 校验值 | `SHA256SUMS`（仓库根） | — |

发布清单中安装包的匹配模式**包含版本号**（`desktop/dist/*Setup {version}.exe`），
因此上一个版本的安装包**不能**满足本版本的清单——这正是 v0.7.1 审计中
「发布清单引用了错误版本的产物」的防护。

---

## 5. 构建时间与提交

| 变量 | 作用 |
| --- | --- |
| `CHEMML_BUILD_COMMIT` | 覆盖 `git_commit()`；用于在无 git 的构建环境中注入提交号 |
| `CHEMML_BUILD_TIME` | 写入 `build_metadata()["built_at"]`，由 CI 注入 |

未提供且不在 git 仓库中时，`git_commit()` 返回字符串 `"unknown"`。
**不允许伪造哈希**——`unknown` 是诚实的答案。

---

## 6. 发布清单

`scripts/release_manifest.py` 是「哪些产物已构建 / 已测试 / 已发布」的唯一权威来源。

- 产物清单在源码中**显式声明**（`ARTEFACTS`），每个条目包含：如何生成、
  需要哪些证据文件、以及是否已发布。
- `tested` 只有在**证据文件存在**时才为真；否则记录缺失了哪些证据。
- `published` 只在本机实际向发布渠道上传后为真。本地构建的场景下它一律为假，
  并注明「未从本机上传到任何发布渠道」——不允许出现「已发布」的乐观推断。
- 每个存在的产物记录 SHA-256、字节数与构建 commit。

```bash
python scripts/release_manifest.py          # 写 docs/RELEASE_MANIFEST.{json,md} 与 SHA256SUMS
python scripts/release_manifest.py --check  # 清单与当前树不一致 -> 退出码 1
```

---

## 7. 发版检查表

发布前必须依次通过：

1. `python scripts/version.py --check` —— 版本一致。
2. `python scripts/lock_dependencies.py --check` —— 锁文件未漂移。
3. `python scripts/quality_gate.py` —— 门禁 PASSED（无 FAIL / TIMEOUT / ERROR）。
4. `python scripts/ci_pipeline.py` —— 12 阶段流水线 PASSED。
5. `python scripts/release_manifest.py` —— 清单与 SHA256SUMS 已更新。
6. `git tag -a v<version> -m "<codename>"`。
7. 发布报告中的**每一个关键数字**都能指向第 3、4 步输出的文件。

> 不允许发布报告引用不存在或无法重新生成的产物（任务书 P0-04 要求 8）。
