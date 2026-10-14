# V0.7 迁移计划（v0.6 → v0.7）

## 原则
1. 增量升级：保留 v0.6 全部经验证功能，不重写可复用代码。
2. 先安全底座（存储/错误/溯源），再桌面化，再能力扩展（Agent/GPU/可视化/报告），最后质量门禁。
3. 每阶段结束运行测试并更新 CHANGELOG 与已知限制。

## 阶段计划与交付物

### Phase A — 基线审计与安全底座 ✅（本仓库内先行完成）
- docs：BASELINE_AUDIT / ARCHITECTURE / MIGRATION_PLAN / TEST_PLAN / KNOWN_LIMITATIONS
- 代码：`storage/`（paths/service/workspace）、`workflow_engine/error_model.py`、`provenance/`（schema/collector）
- 测试：`tests/test_v07_storage.py`、`tests/test_v07_errors.py`、`tests/test_v07_provenance.py`

### Phase B — 桌面应用
- `desktop/`：Electron 主进程（后端 spawn + 健康检查 + 退出清理 + 端口诊断）、preload IPC、启动页
- `desktop/package.json` 构建配置（electron-builder：Windows NSIS；Linux/macOS 配置文件，构建结果如实标注）
- 保持 `npm run dev` 开发模式可用

### Phase C — 文件与节点生态
- `backend/routers/storage.py`：上传/列目录/下载（全部走 StorageService）
- 文件识别：扩展名 + 魔数嗅探，标记 Universal / Vendor Native / Derived
- 节点能力标签（requires_network / requires_gpu / …）加入 `ScientificNode.spec()`
- 插件 manifest 与隔离执行设计文档

### Phase D — Agent 与 AI Router
- `workflow_engine/agent_state.py`：任务状态机 + 非法转移拒绝
- 工具注册表 + 权限检查 + 审计日志
- 路由决策展示（provider/model/原因/是否外发数据）

### Phase E — GPU 与科学可视化
- GPU 状态检测节点（torch/CUDA 真实探测，无 torch 时诚实报 GPU_UNAVAILABLE）
- PyTorch 张量/推理节点（CPU fallback 明确标注实际执行设备）
- 分子 2D 结构（RDKit 可用时）与谱图绘制节点（matplotlib 兜底，PNG/SVG/原始数据导出）

### Phase F — 溯源与报告
- 引擎运行结束时自动写 provenance.json
- 实验记录 + 数据集目录（重复检测）
- Run Diff（两次运行的参数/输入摘要/产物/错误对比）
- DOCX（python-docx）/ Markdown / HTML 导出，导出后完整性校验

### Phase G — 质量门禁与发布
- `scripts/quality_gate.py`：编译/测试/Schema/工作流校验/路径安全/构建/版本一致性/凭据扫描等
- `docs/V07_RELEASE_REPORT.md` + 完整 ZIP 打包

## 兼容性措施
- 所有 v0.6 REST 端点保持原路径与响应结构。
- `config/ai.json`、工作流 JSON、节点注册 API 均向后兼容。
- 测试策略：v0.6 的 62 项测试全部保留且必须继续通过；v0.7 新增测试独立成文件（test_v07_*.py），便于分别统计。
