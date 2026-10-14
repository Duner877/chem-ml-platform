# 桌面运行时与安装包方案（v0.7.2 / 任务 P0-02）

> 本文件回答一个问题：**用户拿到安装包之后，凭什么相信自己能在自己的电脑上跑起来？**
>
> 它记录的是**已实施的方案**、**已声明的支持范围**、以及**哪些平台尚未验证**。

---

## 1. 方案选择：受控安装器（方案 B）

任务书 P0-02 给出两条路径：

| 方案 | 内容 | 本版本选择 |
| --- | --- | --- |
| A 捆绑运行时 | 随包分发 Python 解释器与全部依赖 | **未采用** |
| B 受控安装器 | 检查/安装指定 Python 版本与锁定依赖，失败时给出明确原因 | **采用** |

### 为什么选 B

1. **分发体积与许可证**：捆绑 CPython + SciPy/NumPy/Matplotlib 会把安装包推到数百 MB，并且需要为每个捆绑的二进制组件逐一核对再分发条款（任务书 P1-08 第 4 条）。本版本没有完成该核对，因此不发布可能违规的捆绑物。
2. **可审计性**：受控安装器可以**如实报告**目标机上的真实环境；捆绑运行时一旦打包错误，会把「不兼容」伪装成「可用」——正是任务书 1.1 禁止的行为。
3. **可逆**：卸载不涉及删除用户自行安装的解释器。

### 方案 B 的硬性约束（已实施）

- **不允许把不兼容环境误报为安装成功。** 启动前必须通过完整依赖校验，校验不通过则拒绝启动并给出修复指引。
- **不依赖开发机的绝对路径。** 安装目录、用户数据目录、解释器位置全部在运行时解析。
- **依赖检查必须覆盖完整声明集合**，而不是少数基础包（v0.7.1 只检查了 `fastapi`/`uvicorn`/`pydantic`/`numpy` 四个）。

---

## 2. 支持范围（声明）

| 项目 | 声明值 | 验证状态 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 x64 | **本机构建并通过运行时/端到端检查**；干净虚拟机安装待执行（见 `V07_2_CLEAN_ENV_TEST.md`） |
| 操作系统 | Linux x86_64 | 声明目标，**未验证** |
| 操作系统 | macOS (x64 / arm64) | 声明目标，**未验证** |
| CPU 架构 | x86_64 | 已验证 |
| CPU 架构 | ARM64 | **未验证**（`torch` 的依赖标记已排除该平台） |
| Python | **3.10 ⊆ 版本 < 3.14**（即 3.10 / 3.11 / 3.12 / 3.13） | 已实现，探针强制校验 |
| Node.js（仅构建期） | 22.x | 已验证 |
| Electron | 31.x | 已验证 |

> **未经干净虚拟机验证的平台不得声明为正式支持。** Linux 与 macOS 目前只有 electron-builder 目标配置，没有构建产物，也没有测试记录，因此在 README 与发布报告中一律标注为「声明目标 · 未验证」。

### 依赖范围

依赖被拆分为三组，每组只在各自文件中声明一次（避免版本漂移）：

| 文件 | 作用 | 缺失后的行为 |
| --- | --- | --- |
| `requirements.runtime.txt` | 运行平台所需 | **阻止启动**（`dependencies_missing`） |
| `requirements.dev.txt` | 运行测试所需 | 不影响启动；质量门禁不可用 |
| `requirements.optional.txt` | 加速器与连接器（`torch` 等） | **仅降低能力**，使用内置回退实现 |
| `requirements.txt` | 上述分组的清单（`-r` 引用） | — |

`requirements.txt` 不再直接列出包，只引用分组文件，因此不存在「同一依赖写两遍」的漂移面。

---

## 3. 启动流程与故障分类

### 3.1 启动顺序

```
Electron main
  │
  ├─ 1. 创建用户目录（userData/logs · data · temp · config）
  ├─ 2. 生成会话令牌（每次启动随机）
  ├─ 3. 运行环境探针 runtime-probe.js
  │      └─ 解析解释器 → 校验 requirements.runtime.txt 全量依赖 → 分类
  ├─ 4. 端口检查（8000，冲突则记录并扫描 8000–8019 取空闲端口）
  ├─ 5. 启动 uvicorn backend.app:app（cwd = 应用根，注入令牌与目录变量）
  ├─ 6. 轮询 /api/health（默认 180 s，可由 CHEMML_START_TIMEOUT_MS 覆盖）
  │      └─ 子进程若已退出 → 立即失败（不再空等超时）
  └─ 7. 就绪 → 通知渲染进程
```

### 3.2 故障分类（稳定代码，供 UI 分支处理）

| 代码 | 触发条件 | 用户看到的处理建议 |
| --- | --- | --- |
| `install_failure` | 探针无法执行、启动流程异常终止 | 收集日志并反馈该故障代码 |
| `runtime_missing` | 未找到任何可用 Python 解释器 | 安装受支持版本，或设置 `CHEMML_PYTHON` |
| `dependency_missing` | 解释器版本越界 / 必需依赖缺失或版本不符 | 在安装目录执行 `install.bat` |
| `port_conflict` | 8000–8019 范围内无空闲端口 | 关闭占用程序，或设置 `CHEMML_PORT` |
| `backend_timeout` | 超时上限内 `/api/health` 未就绪 | 首次启动可能正在编译缓存；必要时提高超时上限 |
| `backend_crashed` | 后端进程在就绪前退出 | 查看日志末尾的 Python 异常堆栈 |
| `backend_unstable` | 自动重启预算（3 次）耗尽 | 手动修复后由「后端」菜单重启 |

> 端口被占用**本身不是失败**：会记录占用者、区分是否为本产品实例，然后换端口继续。
> 只有整个扫描范围都无空闲端口时才报 `port_conflict`。

### 3.3 进程生命周期

- `before-quit` / `will-quit` / `process.exit` 三条退出路径都会终止后端子进程树
  （Windows 使用 `taskkill /PID <pid> /T /F`，POSIX 使用 `SIGTERM` 后 `SIGKILL` 兜底）。
- 非预期退出触发最多 3 次自动重启，退避 2 s / 5 s / 10 s；预算耗尽后明确报告
  `backend_unstable`，不再静默重试。
- 重启计数与会话端口写入 `userData/config/session.json`。

---

## 4. 打包规则

`desktop/package.json` 的 `build.extraResources` 决定安装包内容：

| 来源 | 目标 | 说明 |
| --- | --- | --- |
| `../frontend/dist` | `app/frontend/dist` | 前端生产构建产物 |
| `../backend` 等 Python 包 | `app/<pkg>` | 仅 `**/*.py`，排除 `__pycache__` |
| `../node_registry` | `app/node_registry` | 额外包含 `**/*.json`（`registry.json`） |
| `../config` | `app/config` | 仅 `*.json`，**不含** `ai.json`（本地密钥） |
| `../workflows` `../datasets` `../plugins` | `app/...` | 示例工作流、示例数据集、插件目录 |
| `../requirements.txt` 与分组文件 | `app/...` | 依赖清单，供探针与 `install.bat` 使用 |
| `resources/python-runtime` | `python-runtime` | 运行时占位目录（方案 B 下为空，见其中 README） |

**不在安装包内**：用户数据、日志、缓存、`output/`、任何密钥文件。

---

## 5. 数据、日志与卸载策略

| 目录 | 位置 | 内容 |
| --- | --- | --- |
| 安装目录 | 用户选择（NSIS `allowToChangeInstallationDirectory`） | 只读程序文件 |
| 用户数据 | `app.getPath("userData")`（Windows：`%APPDATA%\chemml-desktop` 或产品名对应目录） | 运行数据 |
| 日志 | `<userData>/logs/backend.log`、`security_audit.jsonl` | 后端输出与安全审计 |
| 临时 | `<userData>/temp`（注入 `TEMP`/`TMP`/`TMPDIR`） | 中间产物 |
| 配置 | `<userData>/config/session.json` | 端口等信息（**不含令牌**） |

**卸载数据保留策略**：`nsis.deleteAppDataOnUninstall = false`。

- 卸载**保留** `<userData>` 下的数据、日志与配置，便于排障与升级延续。
- 用户如需彻底清除，需手动删除该目录；卸载程序不会代为删除。
- 这条策略必须在安装说明中明示，不得默认「卸载即清空」。

---

## 6. 安装包校验值

安装包的 SHA-256 由 `scripts/release_manifest.py` 计算并写入根目录 `SHA256SUMS` 与
`docs/RELEASE_MANIFEST.md`。校验方式：

```bash
# Linux / macOS
sha256sum -c SHA256SUMS
# Windows (PowerShell)
Get-FileHash "Chem ML Platform Setup 0.7.2.exe" -Algorithm SHA256
```

> 本版本的 NSIS 安装包在**未提权**的 Windows 构建机上生成，因此**未签名**，
> 并使用 Electron 默认图标（`winCodeSign` 无法在非提权环境解出 macOS 符号链接）。
> 这属于已知限制，不是成功项的伪装——发布材料中如实标注。

---

## 7. 相关文件

| 文件 | 作用 |
| --- | --- |
| `desktop/src/runtime-probe.js` | 运行时探针（可独立 CLI 执行，可被测试） |
| `desktop/src/main.js` | Electron 主进程：启动顺序、故障分类、进程生命周期 |
| `desktop/src/preload.js` | 渲染进程 IPC 表面（含故障与诊断通道） |
| `tests/test_v07_2_desktop_runtime.py` | 探针与打包装配的回归测试 |
| `scripts/clean_env_check.py` | 干净环境 / 端到端检查，产出 `V07_2_CLEAN_ENV_TEST.md` |
| `docs/V07_2_CLEAN_ENV_TEST.md` | 干净环境测试记录（含未执行项） |
| `docs/V07_2_DEPENDENCIES.md` | 依赖版本与可复现安装 |
| `desktop/resources/python-runtime/README.md` | 运行时目录说明（方案 B 下为占位） |
