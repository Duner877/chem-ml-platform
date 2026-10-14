# Pull Request

## 这个 PR 做了什么

<!-- 一两句话说明改动与动机。若关联 Issue，请写 "Closes #123" -->

## 改动类型

- [ ] 缺陷修复
- [ ] 新功能
- [ ] 安全加固
- [ ] 文档
- [ ] 重构（不改变行为）
- [ ] 构建 / CI / 依赖

## 影响面

| 项目 | 值 |
| --- | --- |
| 涉及模块 | |
| 是否改变节点的 `capability_status` / `execution_mode` | <!-- 是 / 否。若是，必须说明依据 --> |
| 是否改变版本号 | <!-- 是 / 否 --> |
| 是否新增第三方依赖 | <!-- 是 / 否。若是，请更新 docs/PROVENANCE.md --> |
| 是否涉及数据集或模型 | <!-- 是 / 否。若是，请更新 docs/PROVENANCE.md 并说明许可 --> |

## 验证证据（必填）

请勾选并粘贴命令输出。**没有证据的 PR 不会被合并。**

- [ ] `python scripts/version.py --check` 通过
- [ ] `python scripts/lock_dependencies.py --check` 通过（若改动了依赖）
- [ ] `python scripts/quality_gate.py` 通过（无 FAIL / TIMEOUT / ERROR）
- [ ] 新增或修改的行为有对应测试
- [ ] 若改动科研节点，已运行 `python scripts/benchmark_lcms.py --strict`

```
（在此粘贴关键命令的输出）
```

## 科研可信性检查（若适用）

- [ ] 该改动**没有**把内部近似算法描述为第三方软件的真实计算。
- [ ] 该改动**没有**把合成基准结果描述为真实数据验证结果。
- [ ] 若声明 `capability_status="verified"`，已提供 `validation_evidence` 且测试真实存在。
- [ ] 若降低某项能力，已如实更新 `limitations`。

## 文档

- [ ] 已更新 `CHANGELOG.md`（面向用户的改动）。
- [ ] 已按需更新 `README.md` / `docs/`。
- [ ] 已按需更新 `docs/PROVENANCE.md`（来源与许可证）。

## 检查

- [ ] 未提交密钥、令牌或本地路径。
- [ ] 未提交 `__pycache__` / `node_modules` / `output/` 等产物。
- [ ] 我的贡献按 Apache-2.0 授权（见 `CONTRIBUTING.md`）。
