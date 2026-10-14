# 运行时目录（v0.7.2 起为占位目录）

## 本版本采用的方案：受控安装器（方案 B）

v0.7.2 明确选择**受控安装器**，**不在此目录捆绑 Python 解释器**。理由与约束见
[`docs/V07_2_DESKTOP_RUNTIME.md`](../../../docs/V07_2_DESKTOP_RUNTIME.md) 第 1 节。

简要说明：

- 捆绑 CPython + SciPy/NumPy/Matplotlib 会把安装包推高到数百 MB，并要求为每个
  捆绑的二进制组件逐一核对再分发许可证——本版本**没有完成该核对**，因此不发布
  可能违规的捆绑物（任务书 P1-08 第 4 条）。
- 受控安装器可以如实报告目标机上的真实环境；捆绑运行时一旦打包错误，就会把
  「不兼容」伪装成「可用」，违反任务书 1.1。

**因此本目录刻意保持为空。** 这不是遗漏，是一个有记录的设计决定。

## 解释器解析顺序（受控安装器）

`desktop/src/runtime-probe.js::resolvePythonCandidates()` 按以下顺序解析：

1. `CHEMML_PYTHON` 环境变量指定的绝对路径（运维/高级用户显式指定）；
2. `resources/python-runtime/python.exe`（本目录——当前为空）；
3. `app/.venv/Scripts/python.exe`（应用载荷内的虚拟环境）；
4. `.venv/` 属于应用根的虚拟环境；
5. `python3` / `python`（`PATH`），**最后才尝试**。

第 5 项排在最后是有意的：**开发者机器上的全局解释器不得被静默当作已声明的运行时**。

## 如何自行切换到方案 A（可选，未来版本）

若将来决定捆绑运行时，需要同时完成：

```bat
REM 1. 下载 CPython "Windows embeddable package (64-bit)"
REM    https://www.python.org/downloads/windows/
REM 2. 解压到本目录
REM 3. 编辑 python3xx._pth，取消注释 "import site"，使 site-packages 生效
REM 4. 安装运行依赖（不是开发依赖）
desktop\resources\python-runtime\python.exe -m ensurepip
desktop\resources\python-runtime\python.exe -m pip install -r requirements.runtime.txt
```

并且**必须**额外完成：

- 枚举 CPython 及其全部再分发组件的许可证，写入 `docs/THIRD_PARTY_LICENSES.md` 与 `NOTICE`；
- 在 `docs/PROVENANCE.md` 记录来源、版本、再分发条件；
- 重新计算 SBOM 并重新生成 `SHA256SUMS`；
- 在干净虚拟机上重新执行 `docs/V07_2_CLEAN_ENV_TEST.md` 的全部项目。

在完成上述工作之前，不得把捆绑运行时描述为已支持的交付形态。
