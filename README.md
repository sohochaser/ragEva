# ragEva

本机单人使用的 RAG 评测工作台。一套 Python 后端分别运行管理 API 与任务 Worker，React 前端独立运行。当前已完成 US-001 工程基座、US-002 金标准数据集导入和 US-003 预测文件导入；评分和样本生成按[用户故事](docs/stories.md)继续实施。

## 本机运行

需要 Python 3.11、[uv](https://docs.astral.sh/uv/)、Node.js 22.12+、npm 和 make。首次克隆后执行：

```sh
make setup
make dev
```

前端默认打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)，管理 API 文档在 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。`make dev` 同时监督 API、Huey Worker 与前端进程；任一进程异常退出时停止其余进程。前端 5173 端口被占用时，Vite 会选择下一个可用端口并在终端显示实际地址。停止命令用 Ctrl-C。

也可在不同终端分别运行 `uv run python -m backend.api`、`uv run python -m backend.worker` 和 `npm --prefix frontend run dev`。管理 API 和前端默认只监听 `127.0.0.1`；Worker 使用本地 SQLite 队列。`GET /api/v1/health/live` 检查 API 进程，`GET /api/v1/health/ready` 在 Worker 不可用时返回 503。

数据集页可上传 UTF-8 CSV/JSONL 金标准样本，创建数据集或导入已有数据集的新版本；支持列名映射、逐行错误提示及版本样本浏览。文件字段、参考 chunk 顺序和版本语义见[导入格式](docs/dataset-format.md)。

预测批次页可导入已有 RAG 系统的 CSV/JSONL 答案与有序检索 chunk，绑定已有数据集版本，或从同一文件同时建立金标准数据集。字段、评测类型和未匹配计数见[预测文件格式](docs/prediction-format.md)。

可选环境变量：`RAGEVA_DATA_DIR`（默认 `.local`）、`RAGEVA_API_HOST`（默认 `127.0.0.1`）、`RAGEVA_API_PORT`（默认 `8000`）、`RAGEVA_API_URL`（前端代理目标，默认 `http://127.0.0.1:8000`）、`RAGEVA_HEARTBEAT_INTERVAL`（默认 2 秒）、`RAGEVA_WORKER_STALE_AFTER`（默认 8 秒）。无效端口或间隔会在启动时报告配置错误。

## 自动化检查

```sh
make check
```

统一检查运行 Python lint/格式/类型/pytest、OpenAPI 快照与生成的前端类型一致性、React lint/类型/组件测试及生产构建。PR 与功能分支上的 GitHub Actions 使用同一命令，不需要模型密钥或真实被测 RAG。修改 API 契约后，依次运行 `uv run python scripts/export_openapi.py` 和 `npm --prefix frontend run generate:api`，再运行 `make check`。

## 文档

- [产品需求](docs/requirements.md)
- [系统架构](docs/architecture.md)
- [开发与验收流程](docs/workflow.md)
- [阶段计划](docs/plan.md)
- [编号用户故事与验收清单](docs/stories.md)
- [金标准数据集导入格式](docs/dataset-format.md)
- [预测文件导入格式](docs/prediction-format.md)
