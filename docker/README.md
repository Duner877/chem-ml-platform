# 部署：Docker（v0.7.4）

`docker/` 目录集中存放生产部署清单。镜像构建配方仍是仓库根目录的
`Dockerfile`（单一来源），本目录提供 compose 编排、反向代理与忽略规则。

## 目录结构

```
docker/
├── docker-compose.yml   # API 必选服务 + 可选的 db / proxy 配置档
├── nginx.conf           # 反向代理：/api、/ws（WebSocket）、静态前端
├── .dockerignore        # 构建上下文排除规则
└── README.md            # 本文件
```

## 快速开始

```bash
# 在仓库根目录准备前端产物（镜像内挂载的是预构建 dist/）
cd frontend && npm install && npm run build && cd ..

# 启动 API + 前端（http://localhost:8000）
docker compose -f docker/docker-compose.yml up --build
```

健康检查：

```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.7.4","nodes":89}
```

## 配置档（profiles）

| 命令 | 服务 | 说明 |
| --- | --- | --- |
| `up --build` | `api` | 必选：FastAPI + 预构建前端，单容器 |
| `--profile db up` | `postgres`, `redis` | 可选：外部持久化 / 缓存（引擎本身不依赖） |
| `--profile proxy up` | `nginx` | 可选：Nginx 前置，终止 HTTP、转发 `/ws` WebSocket，http://localhost:8080 |

```bash
docker compose -f docker/docker-compose.yml --profile db --profile proxy up --build
```

## 不带 compose 的等价命令

```bash
docker build -t chem-ml-platform:0.7.4 .
docker run --rm -p 8000:8000 \
  -e CHEMML_WORKERS=2 \
  -v "$PWD/plugins:/app/plugins" \
  -v chemml-output:/app/output \
  chem-ml-platform:0.7.4
```

## 镜像内容（v0.7.4）

| 层 | 内容 |
| --- | --- |
| 运行时 | `python:3.11-slim` + `libgomp1`，非 root 用户 `chemml` |
| 依赖 | `requirements.txt` 全量（含 CPU 版 PyTorch） |
| 应用 | `backend/ workflow_engine/ data_layer/ models/ simulations/ databases/ nodes/ ai_runtime/ database_runtime/ simulation_runtime/ report_agent/ node_registry/ datasets/ workflows/ node_sdk/` |
| 前端 | `frontend/dist/` 预构建产物，由 FastAPI 作为静态文件托管 |
| 数据卷 | `./workflows` `./datasets` 只读挂载；`./plugins` 可写；`output/` 命名卷 |

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHEMML_HOST` | `0.0.0.0` | 监听地址 |
| `CHEMML_PORT` | `8000` | 监听端口 |
| `CHEMML_WORKERS` | `2` | uvicorn worker 数；单机调试设 `1` 避免事件缓冲分片 |
| `CHEMML_PLUGINS` | `/app/plugins` | 第三方节点插件目录 |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` / `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` | 空 | 启用对应 LLM 供应商；缺省回退内置离线推理 |
| `MP_API_KEY` | 空 | 启用 Materials Project 在线检索 |

**没有密钥也能跑**：LLM 节点回退到内置离线推理器，数据库节点回退本地库，仅在
`metadata["engine"]` 标注来源。密钥通过环境注入，不要写进代码或镜像。

## 生产检查清单

- [ ] `output/` 挂到持久卷，避免容器重建丢产物
- [ ] 暴露公网时按 v0.7.2 的鉴权边界配置：设 `CHEMML_ENV=release` 让其 fail-closed，
      并注入 `CHEMML_SESSION_TOKEN`（或继续在 Nginx / 负载均衡层加认证）。
      **不设令牌时 API 处于 loopback 开放模式**，`GET /api/security/status` 会如实报告 `mode:"off"`，
      不会伪装成已加固部署
- [ ] WebSocket 路径 `/ws` 需开启 `Upgrade` 头（见 `nginx.conf`）
- [ ] `CHEMML_WORKERS` ≥ 2 利用多核；注意事件缓冲按进程分片
- [ ] GPU 场景：PyTorch 为 CPU wheel，需要 GPU 请自建镜像装 CUDA 版
