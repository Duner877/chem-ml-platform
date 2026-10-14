# Chem ML Platform v0.7.2 — 干净环境安装与端到端测试记录

- **codename**: Trusted Delivery Release
- **commit**: `2eb6453b2cec39a2c554e888f527cba7ed5c956d`
- **recorded at**: 2026-10-14T12:01:32+00:00
- **host**: nt · win32 · AMD64
- **python**: 3.13.14
- **node**: C:\Users\hanku\.workbuddy\binaries\node\versions\22.22.2-6\node.EXE
- **结果**: PASS 3 · FAIL 0 · NOT_PERFORMED 0

> 本记录**不把未执行的项目当作通过**。`NOT_PERFORMED` 表示该验证需要本环境不具备的条件，
> 并给出手工执行步骤；在干净虚拟机上完成后应将结果补录到本文件。

## 已验证项目

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 运行时探针校验完整依赖集合 | PASS | classification=ok required=8/8 source=requirements.runtime.txt |
| 不依赖构建机绝对路径 | PASS | 扫描 317 个受控文件，未发现构建机绝对路径 |
| 从非应用目录启动后端（证明不依赖工作目录） | PASS | health ok · 89 个节点 · 示例工作流 04_quantum_chemistry_profiling.json → status=completed run_id=api_58a1cf6aad0a |

## 未执行项目（需要干净虚拟机或图形桌面）

| 项目 | 状态 | 原因与手工步骤 |
| --- | --- | --- |
| 在干净虚拟机中安装 NSIS 安装包 | NOT_PERFORMED | 本环境无法提供干净的目标虚拟机；需在 Windows x64 干净镜像上执行 `Chem ML Platform Setup 0.7.2.exe` 并记录结果。 |
| 首次启动的窗口与前端加载行为 | NOT_PERFORMED | 需要真实桌面会话与安装后的 Electron 进程；本环境无图形桌面。 |
| 卸载后的数据保留行为 | NOT_PERFORMED | 需要真实安装/卸载流程；策略见 docs/V07_2_DESKTOP_RUNTIME.md（deleteAppDataOnUninstall=false）。 |
| 安装目录与用户数据目录的权限与写入验证 | NOT_PERFORMED | 需要真实安装目录（Program Files / 用户目录）的 ACL 环境。 |

## 结论

本机验证覆盖：依赖集合完整性、不依赖构建机绝对路径、从非应用目录启动后端、
以及在真实 HTTP 接口上完成一条端到端示例工作流。

**未覆盖**：目标虚拟机上的安装包安装、首次启动的图形行为、卸载数据保留。
在完成干净虚拟机验证之前，Windows x64 只能声明为「已构建、本机已验证」，
不得声明为「已在干净环境完整验证」。

