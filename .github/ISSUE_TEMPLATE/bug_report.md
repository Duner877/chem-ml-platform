---
name: Bug report / 缺陷报告
about: 报告可复现的缺陷。请填写版本、环境与复现步骤，否则无法定位。
title: "[Bug] "
labels: ["bug"]
assignees: []
---

<!--
请务必填写完整。缺少版本号、环境信息或复现步骤的报告无法被受理
（任务书 P1-09：Issue 模板要求提供版本、环境、复现步骤和日志）。
-->

## 版本与环境

| 项目 | 值 |
| --- | --- |
| 平台版本 | <!-- 例如 0.7.2；见 `/api/health` 的 `version` 字段或界面左上角 --> |
| 安装方式 | <!-- 安装包 / 源码 + install.bat / Docker --> |
| 操作系统 | <!-- Windows 11 x64 / Ubuntu 24.04 / … --> |
| Python 版本 | <!-- `python --version`，或运行时探针报告的值 --> |
| Node 版本（前端/构建） | <!-- `node --version` --> |
| 浏览器 / Electron | <!-- Electron 内或浏览器 + 版本 --> |
| 故障代码 | <!-- 若启动失败，界面会显示代码，如 backend_crashed / dependency_missing --> |

## 复现步骤

1.
2.
3.

## 预期行为

<!-- 你认为应该发生什么 -->

## 实际行为

<!-- 实际发生了什么。如涉及数值，请给出具体数字 -->

## 日志

<!--
请粘贴相关日志。日志位置：
  · 后端日志        <userData>/logs/backend.log
  · 安全审计日志    <userData>/logs/security_audit.jsonl
  · 质量门禁日志    output/gate_logs/*.log
界面中「后端 → 打开日志目录」可直接打开。

请先移除其中的令牌、密钥与个人路径后再粘贴。
-->

```
（在此粘贴日志）
```

## 是否可稳定复现

- [ ] 每次都复现
- [ ] 偶发
- [ ] 只出现过一次

## 附加信息

<!-- 截图、工作流 JSON、数据集等。若与科研结果有关，请附上 provenance 文件 -->
