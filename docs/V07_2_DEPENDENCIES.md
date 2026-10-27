# 依赖锁定与可复现安装（v0.7.2 / 任务 P1-04）

> **目标**：干净环境按文档安装，得到与验证环境一致的依赖图；CPU 默认安装不强制 CUDA；
> 可选依赖缺失时给出清晰的能力降级信息。

---

## 1. 版本基线

| 组件 | 版本 | 来源 |
| --- | --- | --- |
| Python | **3.10 – 3.13**（3.14 起不受支持） | `desktop/src/runtime-probe.js` 强制校验 |
| Node.js（仅构建期） | 22.x | 本机验证 v22.22.2 |
| npm | 10.x | 本机验证 10.9.7 |
| Electron | ^31.0.0 | `desktop/package.json` |
| electron-builder | ^24.13.3 | `desktop/package.json` |
| React / Vite / TypeScript | 见 `frontend/package-lock.json` | 锁文件 |

Python 版本上限为 **3.13**：`torch` 与部分科学二进制轮在 3.14 上的可用性未经核实，
因此不声明支持。探针比较的是 **major.minor**，所以 3.13.x 的任意补丁版本都在范围内
（这是编写本版本测试时发现并修复的真实缺陷）。

---

## 2. 依赖分组

| 文件 | 内容 | 缺失后果 |
| --- | --- | --- |
| `requirements.runtime.txt` | 运行平台所需（web + 科学核心 + 绘图 + DOCX 导出） | **阻止启动** |
| `requirements.dev.txt` | `pytest`、`httpx` | 不影响启动；质量门禁不可用 |
| `requirements.optional.txt` | `torch`（加速器）；`faiss-cpu`（连接器，默认注释） | **仅降级能力** |
| `requirements.txt` | 仅 `-r` 引用上述分组，不重复列包 | — |
| `requirements.lock` | 已解析的**精确版本**（传递闭包） | — |

`requirements.txt` 不再直接列包，因此不存在「同一依赖在两处声明、版本漂移」的失效面。

---

## 3. 可复现安装

### 3.1 用户安装（最小）

```bat
python -m pip install -r requirements.runtime.txt
```

不含测试工具、不含 GPU 依赖。CPU 默认安装**不会**拉入 CUDA。

### 3.2 精确复现验证环境

```bat
python -m pip install -r requirements.lock
```

### 3.3 开发者安装

```bat
python -m pip install -r requirements.txt
cd frontend && npm ci
```

前端必须使用 `npm ci`（严格按锁文件安装），**不要**用 `npm install` 更新锁文件。

### 3.4 可选加速器

```bat
REM CPU wheel（默认）
python -m pip install -r requirements.optional.txt
REM CUDA：先装匹配 CUDA 版本的 torch wheel，再执行上面的命令
```

---

## 4. 锁定文件说明

`requirements.lock` 由 `scripts/lock_dependencies.py` 生成：

- 种子 = `requirements.runtime.txt` + `requirements.dev.txt` 的包名；
- 闭包 = 由**实际安装元数据的依赖图**递归展开（`importlib.metadata.requires`），
  因此不会漏掉传递依赖；
- 输出 = 精确版本 `name==version`。

**它不是解析器**：它固定的是「验证过的环境」，不是「pip 今天会选什么」。
修改任何声明的版本范围后，必须重新生成并重跑质量门禁：

```bat
python scripts/lock_dependencies.py --write
python scripts/quality_gate.py
```

`--check` 会在锁文件与当前环境不一致时以非零退出，质量门禁可以据此拦截漂移。

### 本版本锁定的直接依赖

| 包 | 声明范围 | 锁定版本 |
| --- | --- | --- |
| fastapi | `>=0.110,<1.0` | 0.143.0 |
| uvicorn | `>=0.29,<1.0` | 0.54.0 |
| pydantic | `>=2.6,<3.0` | 2.14.1 |
| numpy | `>=1.26,<3.0` | 2.5.2 |
| scipy | `>=1.11,<2.0` | 1.18.1 |
| networkx | `>=3.2,<4.0` | 3.7 |
| matplotlib | `>=3.8,<4.0` | 3.11.2 |
| python-docx | `>=1.1,<2.0` | 1.2.0 |
| python-multipart | `>=0.0.9,<1.0` | 0.0.32 |
| pytest（dev） | `>=8.0` | 9.1.1 |
| httpx（dev） | `>=0.27` | 0.28.1 |

完整传递闭包共 **37** 个已解析包，见 `requirements.lock`。

---

## 5. CPU / GPU 说明

- **默认安装路径是 CPU**：`requirements.runtime.txt` 与 `requirements.optional.txt` 都不强制 CUDA。
- `torch` 位于可选组；缺失时相关节点使用内置回退实现，能力**降级**而非失败。
- 是否可用 CUDA 由质量门禁的 `host_gpu_status` 阶段如实报告；
  在无 GPU 的机器上该阶段为 `SKIP` 并注明「torch 存在但 CUDA 不可用」，
  **不会**折算为 PASS。
- 平台标记 `platform_system != "Windows" or platform_machine != "ARM64"` 用于排除
  Windows ARM64 上缺少预编译轮的组合。

---

## 6. 外部科研软件（非 pip）

ORCA / Gaussian / Psi4 / CP2K / GROMACS / LAMMPS / OpenMM / VASP / Quantum ESPRESSO
**不是 Python 依赖**，也不随包分发。它们：

- 由 `simulations/controlled.py` 以**可执行文件白名单 + 显式 argv + `shell=False`** 调用；
- 可用性由运行时探针在节点能力层探测（`capability_status=unavailable`）；
- 缺失时 `require_dependencies()` **拒绝执行**，绝不伪装成真实计算完成
  （任务书 P0-05 行为要求 1、4）。

---

## 7. 已知限制

- `requirements.lock` 记录的是**通过 v0.7.4 质量门禁时验证过的确切版本集合**。
  `scripts/lock_dependencies.py --check` 检查的是三件与宿主无关的事：
  每个声明依赖都有对应的 pin、每个 pin 都落在声明范围内、锁文件头部版本与
  `VERSION` 一致。它**不**要求本机当前安装的版本与锁文件逐字相同——
  那是环境事实，不是发布声明；CI 按声明范围安装，解析出的补丁版本自然不同。
  若目标环境的 Python 小版本不同（例如 3.10 vs 3.13），部分包可能需要不同的
  轮文件，此时应回到 `requirements.runtime.txt` 的范围安装，再重跑质量门禁，
  而不是强行安装本锁文件。
- **许可证字符串的写法不是稳定的，比较按语义而非按字面。** 上游会在不改变许可证
  的前提下改写自己的元数据写法，这些改写全部落在本项目的声明范围之内：

  | 依赖 | 较旧版本写法 | 较新版本写法 |
  |---|---|---|
  | fastapi / pydantic | `MIT License` | `MIT` |
  | uvicorn / httpx | `BSD License` | `BSD-3-Clause` |
  | python-multipart | `Apache Software License` | `Apache-2.0` |
  | matplotlib | `PSF` | `Python Software Foundation License` |

  因此 `scripts/license_report.py --check` 判断的是「这两个字符串**指的是同一个许可证
  吗**」，而不是「这两个字符串一样吗」。`scripts/license_report.py` 中的
  `_LICENCE_ALIASES` 显式列出这些同义写法及其对应的精确 SPDX 标识；
  `BSD License` 这类本身不指明修订号的写法，与该家族内的任一精确标识兼容，
  而 `BSD-2-Clause` 与 `BSD-3-Clause` 之间**不**兼容——真实的许可证变更仍会被拦下。
  标识表是写死在代码里的，而不是从某个许可证数据库推导的：后者会让门禁的结论
  取决于运行该检查的机器上装的是哪个数据库版本，那正是本项要消除的那一类
  「随机器而变的结论」。
- 干净环境安装目前只在无虚拟机的本机条件下验证了「不依赖构建机绝对路径」与
  「从非应用目录启动后端」两项，见 `V07_2_CLEAN_ENV_TEST.md`；目标虚拟机上的
  完整安装验证标记为 `NOT_PERFORMED`。
