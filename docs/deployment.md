# 部署指南

三种部署形态：**本地开发**（前后端分离、热重载）、**Docker 单容器**（推荐生产）、**嵌入模式**（`run_local` 进程内执行，无 HTTP）。

## 1. 本地开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ./node_sdk/python

# 终端 1：后端
uvicorn backend.app:app --reload --port 8000

# 终端 2：前端（/api 代理到 :8000）
cd frontend && npm install && npm run dev
```

- 前端：<http://localhost:5173>
- API 文档：<http://localhost:8000/api/docs>
- `--reload` 只重载 Python；新增节点文件需要重启（节点发现发生在启动时）

**健康检查**

```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.7.1","nodes":89}
```

## 2. Docker 单容器

```bash
docker compose up --build
# 打开 http://localhost:8000
```

镜像内容：

| 层 | 内容 |
| --- | --- |
| 运行时 | `python:3.11-slim` + `libgomp1`，非 root 用户 `chemml` |
| 依赖 | `requirements.txt` 全量（含 CPU 版 PyTorch） |
| 应用 | `backend/ workflow_engine/ models/ simulations/ databases/ nodes/ datasets/ workflows/ node_sdk/` |
| 前端 | `frontend/dist/` 预构建产物，作为静态文件由 FastAPI 托管 |
| 数据卷 | `./workflows` `./datasets` 只读挂载；`./plugins` 可写；`output/` 命名卷 |

`HEALTHCHECK` 每 30 秒打一次 `/api/health`；容器异常退出时 `restart: unless-stopped` 自动拉起。

### 2.1 不带 Docker Compose

```bash
docker build -t chem-ml-platform:0.7.1 .
docker run --rm -p 8000:8000 \
  -e CHEMML_WORKERS=2 \
  -v "$PWD/plugins:/app/plugins" \
  -v chemml-output:/app/output \
  chem-ml-platform:0.7.1
```

### 2.2 前端改了之后

Docker 镜像内置的是**预构建**前端，改了 `frontend/src` 必须重新构建：

```bash
cd frontend && npm run build && cd ..
docker compose up --build
```

## 3. 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHEMML_HOST` | `0.0.0.0` | 监听地址 |
| `CHEMML_PORT` | `8000` | 监听端口 |
| `CHEMML_WORKERS` | `2` | uvicorn worker 数；单机调试设 `1` 避免事件缓冲分片 |
| `CHEMML_PLUGINS` | `<repo>/plugins` | 第三方节点插件目录 |
| `PYTHONPATH` | `/app:/app/node_sdk/python` | 容器内已预设，保证 `import chemml_sdk` 可用 |
| `OPENAI_API_KEY` | 空 | 启用 LLM 节点的 OpenAI 供应商 |
| `ANTHROPIC_API_KEY` | 空 | 启用 Anthropic |
| `GOOGLE_API_KEY` | 空 | 启用 Google |
| `DEEPSEEK_API_KEY` | 空 | 启用 DeepSeek |
| `DASHSCOPE_API_KEY` | 空 | 启用阿里通义千问 |
| `MP_API_KEY` | 空 | 启用 Materials Project 在线检索 |

**没有密钥也能跑**：LLM 节点回退到内置离线推理器，数据库节点回退本地库，仅在 `metadata["engine"]` 标注来源。密钥通过环境注入，不要写进代码或镜像：

```bash
export OPENAI_API_KEY=sk-...
docker compose up --build
```

## 4. 插件目录

```bash
mkdir -p plugins
cat > plugins/my_node.py <<'EOF'
from chemml_sdk import ScientificNode, Port, register_node
from workflow_engine.objects import Text

@register_node
class MyNode(ScientificNode):
    name = "My Node"
    category = "Custom"
    description = "示例。"
    output_ports = [Port("text", "Text")]
    def execute(self, inputs, ctx=None):
        return {"text": Text(text="hi")}
EOF

CHEMML_PLUGINS=./plugins uvicorn backend.app:app --port 8000
```

节点在启动时发现一次。运行中热加载需要重启进程（或调 `load_nodes()`）。

## 5. 持久化与备份

| 数据 | 位置 | 备份建议 |
| --- | --- | --- |
| 工作流 | `workflows/*.json` | 随 git 管理 |
| 运行产物 | `output/<run_id>/artifacts/` | 命名卷 / 定期归档；体积大，可只保留报告 |
| 事件历史 | `output/<run_id>/events.jsonl` | 调试用，可定期清理 |
| 结果缓存 | `output/<run_id>/cache/` | 可随时删除，默认关闭 |
| 插件 | `plugins/*.py` | 随 git 管理 |

## 6. 生产检查清单

- [ ] `docker compose --profile db up --build` 未启用时不需要数据库；引擎不依赖外部存储
- [ ] 反向代理（Nginx / Caddy）终止 TLS 并转发到 `:8000`；WebSocket 需开启 `Upgrade` 头
- [ ] `CHEMML_WORKERS` ≥ 2 利用多核；注意事件缓冲按进程分片，跨 worker 的事件回放只覆盖本 worker
- [ ] `output/` 挂到持久卷，避免容器重建丢产物
- [ ] API 默认无鉴权；暴露到公网请在反向代理层加认证
- [ ] GPU 场景：PyTorch 为 CPU wheel，需要 GPU 请自建镜像装 CUDA 版

## 7. 嵌入模式（不启服务）

```python
from chemml_sdk import ChemMLClient

client = ChemMLClient()
result = client.run_local(workflow_dict)   # 进程内执行，零 HTTP
```

适合 CI、Jupyter、把平台当作库嵌进更大的流水线。节点与引擎代码路径完全一致，只是省掉传输层。

## 8. 故障排查

| 现象 | 排查 |
| --- | --- |
| `/api/health` 502 | 后端没起；看 uvicorn 日志 |
| 节点数不是 77 | 插件目录有语法错误的 `.py`，导入被跳过；`python -m custom_nodes.loader --stats`（旧命令 `python -m nodes.loader --stats` 同样可用） |
| 前端 5173 打开但接口全红 | 后端未运行；`vite.config.ts` 的 `/api` 代理指向 `:8000` |
| Docker 构建卡在 pip | 国内网络；给 Docker 配 pip 镜像源 |
| 工作流 422 | `POST /api/workflows/validate` 看具体 issues |
| 插件没出现 | `CHEMML_PLUGINS` 是否指向正确目录；`.py` 是否有 `@register_node` |
