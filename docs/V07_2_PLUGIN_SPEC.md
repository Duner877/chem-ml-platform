# 插件与外部程序执行边界规范（v0.7.2）

> 对应任务书 **P1-03（插件与外部程序执行边界）** 与 **P2-04（面向开发者的插件规范）**。
>
> 本文档描述**当前版本实际实现了什么**。凡是未实现的隔离能力，本文档明确写为「未实现」，
> 并说明原因；不把进程级隔离描述成操作系统级安全沙箱。

---

## 1. 两类扩展点

平台有两种性质完全不同的扩展方式，安全边界也因此不同：

| 类型 | 加载方式 | 运行位置 | 信任级别 |
|---|---|---|---|
| **节点插件** | `plugins/` 目录，由 `chemml_sdk.load_nodes()` 导入 | 与后端**同一进程** | 视为**受信任代码** |
| **外部科研软件** | `simulations/controlled.py` 的 `ControlledRunner` 启动子进程 | 独立子进程 | 视为**不可信输入的执行者** |

**关键结论（不可宣传为沙箱）**：节点插件是 Python 模块，与后端同进程运行，
因此**没有任何进程隔离**。只有外部科研软件走子进程路径，具备进程级隔离
（工作目录、超时、输出上限、并发上限、清理），但**仍不是操作系统级安全沙箱**。

---

## 2. 节点插件规范（P2-04）

### 2.1 最小可运行插件

```python
# plugins/my_lab/nodes.py
from chemml_sdk import ParameterSpec, Port, ScientificNode, register_node


@register_node
class MyDesaltingNode(ScientificNode):
    """一句话说明该节点做什么。"""

    # --- 身份 ---------------------------------------------------------- #
    type = "MyDesaltingNode"          # 全局唯一的类名，工作流 JSON 用这个名字
    label = "脱盐处理"                 # 界面显示名
    category = "预处理"
    version = "0.7.2"

    # --- 端口 ---------------------------------------------------------- #
    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [Port("spectrum", "Spectrum", "脱盐后的谱图")]

    # --- 参数 ---------------------------------------------------------- #
    parameters = [
        ParameterSpec("threshold", "float", 0.01, "阈值",
                      min=0.0, max=1.0, step=0.001, unit="a.u."),
        ParameterSpec("mode", "enum", "soft", "模式",
                      options=[("soft", "柔和"), ("hard", "强阈值")]),
    ]

    # --- v0.7.2（任务 P0-05）：执行声明，缺一不可 ----------------------- #
    capability_status = "executable"          # verified|executable|experimental|unavailable
    execution_mode = "internal_approximation"  # external|internal_approximation|synthetic_demo
    reproducibility_level = "deterministic"   # deterministic|seeded|nondeterministic
    deterministic = True
    input_constraints = "仅接受一维 Spectrum；不接受 NaN 强度。"
    limitations = ["未做基线校正，只做阈值截断。"]
    validation_evidence = []                  # 为空则永远不会被判为 verified

    def execute(self, inputs, ctx):
        spectrum = inputs["spectrum"]                 # 必选端口可直接取
        threshold = self.get_param("threshold")
        mode = self.get_param("mode")
        self.log(f"脱盐 threshold={threshold} mode={mode}")
        return {"spectrum": _desalt(spectrum, threshold, mode)}
```

### 2.2 声明字段的强制规则

这些规则由 `node_registry/validator.py` 与 `workflow_engine/node_base.py` 在执行期
强制，违反会导致注册表校验失败或能力被降级：

| 字段 | 允许取值 | 强制规则 |
|---|---|---|
| `capability_status` | `verified` / `executable` / `experimental` / `unavailable` | 标为 `verified` **必须**同时给出非空 `validation_evidence`，否则被自动降级 |
| `execution_mode` | `external` / `internal_approximation` / `synthetic_demo` | 与 `capability_status` 不匹配时降级为 `internal_approximation`，并附降级原因 |
| `reproducibility_level` | `deterministic` / `seeded` / `nondeterministic` | `seeded` / `nondeterministic` 必须暴露 `seed` 参数 |
| `required_dependencies` | 形如 `"orca >= 5.0"` 的字符串列表 | 依赖缺失时抛 `DependencyMissingError`，**不得**返回伪造结果 |

枚举校验在 `ParameterSpec.coerce()` 中同时匹配 `value` 与 `label`；
两者都不匹配时会回退到首个选项，因此**不要**依赖错误的枚举值触发报错。

### 2.3 插件权限声明

节点通过以下字段声明它需要什么，扫描器（`node_registry/scanner.py`）把它汇总进
`registry.json`，界面与报告据此展示：

| 声明 | 含义 | 可执行性检查 |
|---|---|---|
| `capabilities` | 能力标签（如 `quantum`、`spectrum`） | 静态 |
| `required_software` | 需要的外部可执行文件名 | 运行时 `shutil.which` 探测 |
| `required_dependencies` | 人类可读的依赖与版本下限 | 文档 + 报告 |
| `external_software` | 实际调用的程序与版本 | 运行后写入溯源 |

`node_registry/capabilities.py::node_status()` 给出**运行时**判定：
外部程序缺失的节点报告为 `unavailable` 并列出缺失程序，**不会伪装执行成功**。

### 2.4 插件作者必须遵守的约束

1. **不得调用 `subprocess` 直接启动外部程序** —— 必须经 `ControlledRunner`。
2. **不得读取声明之外的文件**（见 §3.4 的如实说明）。
3. **不得在导入期执行有副作用的工作** —— `load_nodes()` 会导入所有插件。
4. **科学计算固定随机种子**；结果缓存默认关闭（`use_cache=False`）。
5. **产物按 id 命名，不覆盖同名文件**。

---

## 3. 外部程序执行边界（P1-03）

实现文件：`simulations/controlled.py`。

### 3.1 白名单

只有下列 9 个程序可按**逻辑名**启动，调用方**不能**传入任意路径：

| 逻辑名 | 可执行文件 | 领域 | 许可 |
|---|---|---|---|
| `orca` | orca | 量子化学 | 需用户自行获取 |
| `gaussian` | g16 | 量子化学 | 商业许可 |
| `psi4` | psi4 | 量子化学 | LGPL-3.0 |
| `cp2k` | cp2k.psmp | 量子化学 | GPL-2.0 |
| `gromacs` | gmx | 分子动力学 | LGPL-2.1 |
| `lammps` | lmp | 分子动力学 | GPL-2.0 |
| `openmm` | python（经其 Python API 调用） | 分子动力学 | MIT |
| `vasp` | vasp_std | 材料 | 商业许可 |
| `quantum_espresso` | pw.x | 材料 | GPL-2.0 |

请求白名单之外的程序抛出 `ExternalToolNotAllowed`。

### 3.2 参数传递

* `subprocess` 一律以**参数列表**调用，`shell=False`。
* 代码库中**不存在** `shell=True`；由 `scripts/quality_gate.py::stage_credentials`
  的同级静态检查与人工审计共同保证（`grep -rn "shell=True"` 无命中）。
* 因此 shell 元字符（`;` `|` `&&` `$()`）**不会被解释**，非法参数不会造成任意命令执行。

### 3.3 资源与生命周期控制

| 控制项 | 实现 |
|---|---|
| 工作目录 | 每次调用独占 scratch 目录，任务之间互不干扰 |
| 超时 | `timeout` 参数；超时抛错，任务被终止并标记 |
| 输出上限 | 输出字节上限，超出即停止读取 |
| 并发上限 | 信号量限流，避免一次性拉起过多重型进程 |
| 清理 | 成功、失败、超时、取消**四条路径**都会删除 scratch 目录 |
| 版本探测 | `describe_tools()` 返回每个程序的安装状态、路径与版本 |

### 3.4 本版本未实现的能力（如实声明）

| 能力 | 状态 | 说明 |
|---|---|---|
| 操作系统级沙箱（seccomp / AppContainer / SELinux） | **未实现** | 仅进程级隔离。**不得**对外描述为「强安全沙箱」 |
| 文件系统访问限制 | **未实现** | 插件与后端同进程，可访问进程可读的任何文件 |
| 网络访问限制 | **未实现** | 插件可发起网络请求 |
| 插件签名与来源校验 | **未实现** | 只加载 `plugins/` 目录下的代码，依赖部署方的目录权限 |
| 高风险操作的用户确认弹窗 | **部分实现** | 执行外部程序前有界面提示；无独立的二次确认流程 |

**结论**：当前版本的安全模型是「**受信任插件 + 受控外部调用**」，
而非「不可信插件沙箱」。部署方必须自行保证 `plugins/` 目录的写入权限可控。

---

## 4. 开发者上手步骤

```bash
# 1. 安装（开发环境）
python -m pip install -r requirements.txt
python -m pip install -e ./node_sdk/python

# 2. 写一个节点
mkdir -p plugins/my_lab && $EDITOR plugins/my_lab/nodes.py   # 参照 §2.1

# 3. 校验声明是否合法（缺字段会直接报错）
python -m node_registry --write
python -m node_registry --check

# 4. 重新生成目录与统计，确认 README 与注册表一致
python scripts/node_catalog.py --check

# 5. 跑最小测试
python -m pytest -m unit
python scripts/smoke_nodes.py --quiet
```

Node.js / TypeScript 侧接口见 `node_sdk/nodejs/`，用法见该目录 `README.md`。

---

## 5. 验收对照

| 任务书验收标准 | 证据 |
|---|---|
| 非法参数不会导致任意命令执行 | 白名单 + 参数列表 + `shell=False`；`grep -rn "shell=True"` 全库无命中；`tests/test_v07_1_capabilities.py::TestControlledRunner::test_no_shell_interpretation` |
| 超时任务会被可靠终止或标记为终止失败 | `tests/test_v07_1_capabilities.py::TestControlledRunner::test_timeout_terminates_the_child_and_cleans_up`（子进程心跳计数在超时后停止增长，证明进程确被终止）与 `::test_timeout_cleans_the_scratch_directory` |
| 插件权限声明与实际可用能力一致 | `node_registry/capabilities.py::node_status()`；89 节点全量能力普查见 `output/gate_logs/node_registry_provenance.log` |
| 未实现操作系统级隔离时不得宣传为强安全沙箱 | 本文档 §3.4 明确列为「未实现」 |

> 相关实现：`simulations/controlled.py`、`node_registry/capabilities.py`、
> `node_registry/scanner.py`、`node_registry/validator.py`、`node_sdk/python/chemml_sdk/`。
> 节点来源与许可记录见 `docs/PROVENANCE.md`。
