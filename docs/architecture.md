# 系统架构草案

状态：架构草案。采用前后端分离的单仓库，一套 Python 后端和一个 React 前端通过版本化 HTTP API 通信。首版面向本机单人使用；API 进程与 Worker 使用同一套 Python 后端代码，分别承担交互请求和异步评测任务。

US-001 已落地的运行基座：`backend/api/` 与 `backend/worker/` 是两个独立进程；Worker 监督 Huey SQLite consumer，并把心跳写入本机数据目录的 `health.sqlite3`。管理 API 的 `/api/v1/health/live` 只检查自身，`/api/v1/health/ready` 根据 Worker 进程及心跳是否新鲜返回 200 或 503。心跳库与任务队列分离，当前不承载业务数据。前端由 Vite 独立服务，开发代理访问管理 API；契约快照为 `contracts/openapi.json`，前端类型由它生成。

```text
React + TypeScript
    |
    | /api/v1 (JSON)
    v
Python API (FastAPI)
    |-- 数据集、候选审核、目标配置、预测结果导入、运行、结果 API
    |-- 本机配置与密钥引用
    |
    +--> SQLite (文档清单、数据集、预测结果、运行与评分)
    +--> SQLite 任务队列 --> Python Worker
                            |-- HTTP JSON/SSE 调用或导入结果读取
                            |-- 文档样本候选生成与查重
                            |-- 统一预测结果模型
                            |-- chunk 语义匹配与检索指标
                            |-- LLM 指标适配器
                            +-- 运行结果与调用轨迹

远程被测 RAG -- 独立 Token --> Python 下载入口 (独立监听)
                              +--> 文档清单与原始文件存储
```

## 组件边界

- `frontend/`：React + TypeScript。文档上传与下载配置、数据集、生成候选审核、输入方式、系统连接、预测结果导入、场景评价标准配置、运行、总体与逐样本结果视图；不持有第三方 API 密钥。
- `backend/api/`：FastAPI、输入校验和契约序列化；不直接执行长评测任务。
- `backend/download/`：只提供原始文档清单和文件的独立 ASGI 入口，使用专用 Token，可单独监听远程可达地址；不挂载管理 API。
- `backend/domain/`：文档集合快照、候选审核与发布、数据集版本、指标输入输出、运行状态机与结果聚合规则；不依赖 Web、数据库或队列框架。
- `backend/adapters/`：目标 RAG HTTP JSON/SSE 协议、CSV/JSONL 导入、原文解析、在线生成与评分模型、本地向量模型和持久化实现。HTTP 与文件适配器产出同一预测结果模型。
- `backend/worker/`：样本生成与评测调度、限流、重试、取消、token 用量记录和结果落库。队列实现可替换；初版选成熟组件，避免自制任务系统。
- `contracts/`：OpenAPI 和可共享的示例请求、响应；前端类型由契约生成。

依赖方向：API/Worker -> 领域服务 -> 端口接口；适配器实现端口。前端只依赖公开 API 契约。

## 核心实体

`DocumentCollection`、`SourceDocument`、`SourceChunk`、`GeneratedCandidate`、`GenerationRun`、`Dataset`、`DatasetVersion`、`EvaluationCase`、`TargetConfig`、`PredictionBatch`、`Prediction`、`MetricConfig`、`EvaluationScenario`、`EvaluationRun`、`ChunkMatchDecision`、`CaseResult`、`MetricResult`、`ModelUsage`。文档集合在导入完成后形成不可变快照；原始文档保留文件字节、`document_id` 与校验值，切块配置和结果随快照保存。MVP 不更新文档内容。生成任务保存目标条数、多 chunk 比例、语言、题型、补充要求与核心提示词版本；候选记录支撑 chunk 与审核、查重判定。只有审核通过、完成查重和字段校验的候选才能创建数据集或发布已有数据集的新版本。HTTP 调用和文件导入都生成不可变 `PredictionBatch`，评分运行引用该批次。一个场景包含三项回答指标可编辑的评价标准；系统提示词结构和输出格式由代码版本控制。运行选择一个场景，并保存数据集版本、预测批次及来源快照、指标配置与版本、场景标准及系统提示词版本快照、回答模型和本地向量模型的标识及非敏感参数、相似度阈值、开始/结束时间和状态。逐样本保留答案、检索片段引用、耗时、评分、错误与证据。`ChunkMatchDecision` 保存参考与预测 chunk、余弦相似度、阈值和匹配判定，供复评与审查复用。`ModelUsage` 区分实际与估算输入/输出 token；密钥只保存受保护的引用，不进入导出文件。

规范化样本有 `case_id` 和 `question`。端到端答案样本携带 `reference_answer`；检索样本携带有序 `reference_chunks`；同一题可以同时带两类标注，也可只带其中一种。每个参考 chunk 记录正文和所属 `document_id`，列表位置即从高到低的参考相关性顺序；不要求共享 chunk ID 或数值相关性分数。规范化预测包含 `case_id`，以及按评测类型提供的 `answer` 和按预测检索顺序排列的 `contexts`；检索评测必须有 `contexts`，答案评测必须有 `answer`，需要计算忠实度时还必须有 `contexts`。每个预测 chunk 包含正文和 `document_id`，可附带片段 ID、来源及耗时。HTTP 与文件适配器都输出这一结构。检索匹配先用文档 ID 限定候选，再用同一模型的余弦相似度和阈值建立候选边；文档 ID 相同不能直接算命中。

检索评分器对 K=10、20 分别取预测 Top-K，在候选二部图上计算最大命中数的一对一匹配。多解时依预测位置、参考相关性顺序、相似度、输入位置稳定决议；正文规范化后完全相同的重复预测项只有首次出现者可参与匹配。`ChunkMatchDecision` 按 K 记录候选边、阈值、选中配对与排除原因。匹配和增益规则版本写入运行快照，避免重新评分改变旧结果。逐样本计算 Precision@K、AP@K、NDCG@K；运行级 MAP@K 是有效检索样本 AP@K 的平均值。参考位置 r 在总数 m 中使用线性增益 `m-r+1`，按预测位置对数折损计算 NDCG；指标公式与边界验收见 `requirements.md`。

## 运行状态与一致性

运行状态为 `queued -> running -> completed | failed | cancelled`。每个样本有独立状态；重复投递以运行 ID + 样本 ID 幂等写入。仅成功完成的样本计入相应指标聚合，报告必须同时显示有效样本数、失败数和不适用数。

## API 草案

被测 RAG 服务的首版通用契约为 `POST {target_url}`，请求 JSON 为 `{"case_id": "...", "question": "..."}`，典型非流式响应 JSON 为 `{"answer": "...", "contexts": [{"document_id": "...", "text": "...", "chunk_id": "...", "source": "..."}]}`。请求增加 `stream: true` 时使用 SSE；适配器拼接 `answer.delta`，收集 `contexts`，要求成功结束事件后才生成规范化预测结果，流内错误和意外断流保留失败原因。事件字段、TTFT 与 TTLT 的定义见 `requirements.md`。`answer` 和 `contexts` 按评测类型校验；检索评测必须有 `contexts`，回答评测必须有 `answer`，忠实度还需要 `contexts`。`contexts` 顺序即预测检索排序，每个 chunk 的 `document_id` 与 `text` 必填，`chunk_id`、`source` 可选。目标可选返回 `usage` 中的输入与输出 token 数；SSE 在 `completed` 事件中提供该值，未提供时不估算其内部用量。连接测试校验相应契约，调用耗时由评测系统测量。后续真实系统协议通过适配器转换到规范化预测模型。

生成与评测运行、样本、预测批次与重试尝试关联 OpenTelemetry trace ID；API 到 Worker 的队列消息传递 trace 上下文。Jaeger 只保存 ID、耗时、token、状态、脱敏配置及错误摘要，默认保留 30 天且可配置；全文保存在候选或评测结果中直到用户删除。trace 过期不影响历史结果查看，凭据及认证头不进入 trace。

- `POST /api/v1/datasets/import`，`GET /api/v1/datasets/{id}/versions`
- `POST /api/v1/document-collections`：上传 TXT/Markdown/DOCX/文本 PDF 或导入已有 chunk 清单；原文提取、切块与 `document_id` 校验后形成不可变快照。
- `POST /api/v1/document-collections/{id}/generations`，`GET /api/v1/generations/{id}/candidates`：生成任务接收目标条数、多 chunk 比例、语言、题型和补充要求，返回实际数量、失败原因和 token 用量。
- `PATCH /api/v1/candidates/{id}`，`POST /api/v1/candidates/publish`：审核、校验并发布不可变数据集版本。
- `POST /api/v1/targets`，`POST /api/v1/targets/{id}/test`
- `POST /api/v1/predictions/import`，`GET /api/v1/predictions/{id}`
- `GET /api/v1/scenarios`，`POST /api/v1/scenarios`，`PUT /api/v1/scenarios/{id}`，`POST /api/v1/scenarios/{id}/preview`
- `POST /api/v1/runs`，`GET /api/v1/runs/{id}`，`POST /api/v1/runs/{id}/cancel`
- `POST /api/v1/runs/{id}/rescore`：复用原运行的预测批次，使用所选场景模板创建新评分运行。
- `GET /api/v1/runs/{id}/results`，`GET /api/v1/runs/{id}/export`

接口路径是设计草案；实现前用 OpenAPI 样例和契约测试固定字段、错误码及分页规则。

独立下载入口提供 `GET /download/v1/collections/{id}/manifest` 与 `GET /download/v1/documents/{id}/file`，两者都校验专用 Bearer Token。清单包含被测 RAG 导入时使用的 `document_id`、文件名、校验值及对应文件下载 URL；文件接口只返回上传时的原始字节。只导入 chunk 清单的集合没有原文下载。监听地址与对外 URL 可配置，公网或内网路由由部署环境提供；管理 API 继续只监听回环地址，且不跟踪被测系统的文档导入状态。

## 技术取舍

首版使用 SQLite 保存本机数据，并使用 Huey 的 SQLite 队列驱动独立 Python Worker，无需单独运行 PostgreSQL 或 Redis。用户数据和原始文档保存在可配置的本机目录，管理 API 默认仅绑定 `127.0.0.1`。样本生成与回答评测分别调用可配置的在线 OpenAI 兼容 API；独立的本地向量模型适配器批量生成参考与预测 chunk 向量，按模型版本和正文缓存。向量权重首次可下载缓存，也可从本地目录加载；检索评测不调用生成式模型或 SaaS 向量服务。同一文档 ID 内计算余弦相似度，并使用与模型绑定的阈值生成可审查的匹配候选。在线服务返回 usage 时记录实际输入/输出 token，否则以本地分词器估算并标记；本地向量生成记录输入 token，输出 token 标记不适用。Ragas 等现有评测库承接回答指标，在本项目适配层固定指标版本与提示词。所有模型调用都可替换为测试桩，以便 CI 不依赖付费服务。
