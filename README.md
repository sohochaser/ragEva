# ragEva

本机单人使用的 RAG 评测工作台。一套 Python 后端运行管理 API、任务 Worker 与独立文档下载进程，React 前端独立运行。已实现的故事按[用户故事](docs/stories.md)和本地 Git 提交跟踪。

## 本机运行

需要 Python 3.11、[uv](https://docs.astral.sh/uv/)、Node.js 22.12+、npm 和 make。首次克隆后执行：

```sh
make setup
make dev
```

前端默认打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)，管理 API 文档在 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。`make dev` 同时监督 API、Huey Worker 与前端进程；任一进程异常退出时停止其余进程。前端 5173 端口被占用时，Vite 会选择下一个可用端口并在终端显示实际地址。停止命令用 Ctrl-C。

也可在不同终端分别运行 `uv run python -m backend.api`、`uv run python -m backend.worker` 和 `npm --prefix frontend run dev`。管理 API 和前端默认只监听 `127.0.0.1`；Worker 使用本地 SQLite 队列。`GET /api/v1/health/live` 检查 API 进程，`GET /api/v1/health/ready` 在 Worker 不可用时返回 503。

数据集页可上传 UTF-8 CSV/JSONL 金标准样本，创建数据集或导入已有数据集的新版本；支持列名映射、逐行错误提示及版本样本浏览。文件字段、参考 chunk 顺序和版本语义见[导入格式](docs/dataset-format.md)。

文档集合页可批量上传 UTF-8 TXT/Markdown、DOCX 和可提取文本的 PDF 原文，逐文件填写 `document_id` 或按文件名称自动编号。切块大小为 1–10000 字符，重叠量须小于切块大小。集合保存上传原始字节、SHA-256、切块配置与有序切块，并可在详情页核对；任何文件有误时整个集合不创建。扫描版或受保护 PDF 无法导入，系统不执行 OCR。也可导入 UTF-8 CSV/JSONL chunk 清单，每行包含从 0 连续递增的 `position`、`document_id` 和 `text`；这类集合保留清单全局顺序并标记无原文，不提供文件下载。

### 独立原文下载

设置专用 Token 后，在另一个终端启动下载进程。它与管理 API 共用 `RAGEVA_DATA_DIR` 中的集合快照，但只提供清单和原始文件，不暴露管理 API。

```sh
RAGEVA_DOWNLOAD_TOKEN='<专用 Token>' uv run python -m backend.download
```

默认监听 `127.0.0.1:8001`。远程访问时配置 `RAGEVA_DOWNLOAD_HOST`（监听地址）、`RAGEVA_DOWNLOAD_PORT` 和 `RAGEVA_DOWNLOAD_PUBLIC_URL`（远程客户端可访问的 HTTP(S) 基础 URL，例如 `https://files.example.test`）；网络和 TLS 由部署环境提供。下载进程缺少 Token 时拒绝启动。持 Token 请求 `GET /download/v1/collections/{集合 ID}/manifest`，再按清单中的 `download_url` 请求文件，两次请求均需 `Authorization: Bearer <专用 Token>`。清单包含上传时固定的 `document_id`、文件名和 SHA-256；文件返回上传时的原始字节。chunk-only 集合的清单标为 `chunks_only` 且没有文件项。

候选生成页可配置独立的在线 OpenAI 兼容模型，选择任一文档集合，指定目标条数、多 chunk 比例、语言和题型，异步生成待审核候选。添加或修改模型时会实际调用一次 Chat Completions 接口验证模型、地址、凭据和 JSON 响应；校验失败不保存。页面可编辑或删除空闲模型，在途任务引用的模型暂不可改删。页面显示进度、实际/目标数量、失败与不足额原因，并保留每题引用的集合 chunk。审核者可在候选项中修改问题、答案，增删和重排当前集合的参考 chunk，保存修订、批准或驳回，并查看历史。同集合查重自动比较历次候选和已发布快照；明确重复阻止发布，疑似重复须填写放行理由。已批准且通过查重的候选可发布为新数据集或加入已有数据集的新版本，旧版本仍可读取。模型 Token 单独保存在受保护的本机文件中，不进入任务快照。配额、审核、查重与发布规则见[候选生成说明](docs/generations.md)。

预测批次页可导入已有 RAG 系统的 CSV/JSONL 答案与有序检索 chunk，绑定已有数据集版本，或从同一文件同时建立金标准数据集。字段、评测类型和未匹配计数见[预测文件格式](docs/prediction-format.md)。

有参考及预测 chunk 的样本可在预测批次页调用本地向量模型预览相似度与阈值判定。默认中文模型首次使用会下载权重；缓存、离线模式和模型专属阈值见[本地匹配说明](docs/local-matching.md)。

可选环境变量：`RAGEVA_DATA_DIR`（默认 `.local`）、`RAGEVA_API_HOST`（默认 `127.0.0.1`）、`RAGEVA_API_PORT`（默认 `8000`）、`RAGEVA_API_URL`（前端代理目标，默认 `http://127.0.0.1:8000`）、`RAGEVA_HEARTBEAT_INTERVAL`（默认 2 秒）、`RAGEVA_WORKER_STALE_AFTER`（默认 8 秒）。无效端口或间隔会在启动时报告配置错误。

评测运行、目标采集和候选生成支持 OpenTelemetry trace 关联；配置 OTLP HTTP 接收端和 Jaeger UI 后，结果页可打开对应 trace，并按默认 30 天或自定义保留期提示过期。配置与隐私边界见[全链路 trace](docs/tracing.md)。

## 自动化检查

```sh
make check
```

统一检查运行 Python lint/格式/类型/pytest、OpenAPI 快照与生成的前端类型一致性、React lint/类型/组件测试、生产构建及 Playwright 浏览器关键路径测试。浏览器测试在 macOS 上可使用已安装的 Google Chrome；其他环境先运行 `npm --prefix frontend exec -- playwright install chromium`。GitHub Actions 会安装 Chromium 并执行同一 `make check`，不需要模型密钥或真实被测 RAG。修改 API 契约后，依次运行 `uv run python scripts/export_openapi.py` 和 `npm --prefix frontend run generate:api`，再运行 `make check`。

## 文档

- [产品需求](docs/requirements.md)
- [系统架构](docs/architecture.md)
- [开发与验收流程](docs/workflow.md)
- [阶段计划](docs/plan.md)
- [编号用户故事与验收清单](docs/stories.md)
- [自动化测试案例说明](docs/automated-test-cases.md)
- [金标准数据集导入格式](docs/dataset-format.md)
- [预测文件导入格式](docs/prediction-format.md)
- [本地向量匹配预览](docs/local-matching.md)
- [候选生成说明](docs/generations.md)
- [全链路 trace 与保留期](docs/tracing.md)
