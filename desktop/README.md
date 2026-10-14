# Chem ML Platform — 桌面应用（Electron）

v0.7.1 任务 A：把桌面外壳从「依赖开发机环境的外壳」升级为「包含后端与运行时定位的完整交付链路」。

## 1. 交付结构（打包后 `resources/`）

| 目录 | 内容 |
| --- | --- |
| `app/` | Python 后端与全部节点包（`backend/` `nodes/` `workflow_engine/` `simulations/` `models/` `foundation/` `ai_runtime/` `data_layer/` `simulation_runtime/` `database_runtime/` `databases/` `provenance/` `storage/` `report_agent/` `report_engine/` `agent_runtime/` `node_registry/` `memory/` `config/` `plugins/` `datasets/` `workflows/` `static/` `requirements.txt`） |
| `frontend-dist/` | 前端生产构建（`frontend/dist`） |
| `python-runtime/` | 可选：随应用分发的独立 Python 解释器（见该目录下 README） |

配置见 `desktop/package.json` 的 `build.extraResources`。

## 2. 运行时定位顺序（`src/main.js`）

1. `resources/python-runtime/python.exe`（随应用打包，完全自包含）
2. `resources/app/.venv/Scripts/python.exe`（随包 venv）
3. 仓库 `.venv`（仅开发）
4. `PATH` 上的 `python`（兜底，并在诊断中如实标注）

后端根目录：打包后为 `resources/app`；开发时为仓库根。

## 3. 用户数据 / 日志 / 临时目录

全部位于 `app.getPath("userData")` 下，**不写入安装目录**，因此卸载/升级不会误删数据：

```
<userData>/
├── logs/    backend.log · security_audit.jsonl
├── data/    uploads/ 等运行数据
├── temp/    外部程序 scratch
└── config/  session.json（仅端口，不含令牌）
```

NSIS 安装器设置 `deleteAppDataOnUninstall: false`，卸载保留用户数据。

## 4. 首次启动诊断（P0-02 验收）

启动时执行一次依赖探测：确认解释器可运行，并逐一 `import fastapi / uvicorn / pydantic / numpy`。任一缺失或解释器不可用，会**弹出可操作的错误对话框**（含缺哪个依赖、后端目录、日志路径、常见原因），而不是显示空白窗口。

## 5. 本地 API 认证（任务 D）

主进程每次启动生成随机 `sessionToken` / `readonlyToken`，通过环境变量 `CHEMML_SESSION_TOKEN` / `CHEMML_READONLY_TOKEN` 交给后端，并把令牌经 preload 的 `contextBridge` 注入渲染进程（`window.__CHEMML_TOKEN__`），前端 `api.ts` 自动附带 `X-ChemML-Token` 头。令牌只存在于内存与进程参数，不写入安装目录。

## 6. 构建

```bat
cd desktop
npm install
npm run build        REM Windows NSIS 安装包 → desktop/dist
npm run build:linux  REM AppImage / tar.gz
npm run build:mac    REM dmg
npm start            REM 开发模式（需仓库根已有 .venv 与 frontend/dist）
```

## 7. 已知限制

- Linux / macOS 安装包配置已提供，但未在对应平台实测（见 `docs/V07_KNOWN_LIMITATIONS.md`）。
- 未放置 `python-runtime/` 时，目标机需自备 Python 3.11+ 与后端依赖；首次启动诊断会明确提示。
