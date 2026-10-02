# 系统架构草案

状态：架构草案。采用前后端分离的单仓库，一套 Python 后端和一个 React 前端通过版本化 HTTP API 通信。首版面向本机单人使用；API 进程与 Worker 使用同一套 Python 后端代码，分别承担交互请求和异步评测任务。

US-001 已落地的运行基座：`backend/api/` 与 `backend/worker/` 是两个独立进程；Worker 监督 Huey SQLite consumer，并把心跳写入本机数据目录的 `health.sqlite3`。管理 API 的 `/api/v1/health/live` 只检查自身，`/api/v1/health/ready` 根据 Worker 进程及心跳是否新鲜返回 200 或 503。心跳库与任务队列分离，当前不承载业务数据。前端由 Vite 独立服务，开发代理访问管理 API；契约快照为 `contracts/openapi.json`，前端类型由它生成。

US-002 已落地的数据集边界：`backend/adapters/dataset_files.py` 读取 CSV/JSONL，`backend/domain/datasets.py` 校验规范化样本，`backend/adapters/dataset_store.py` 在单个 SQLite 事务中写入数据集和版本。每次导入是完整版本快照，旧版只读；`backend/api/datasets.py` 提供导入、列表与分页读取。React 数据集页经生成的 OpenAPI 类型访问这些接口。当前业务库为数据目录下的 `rageva.sqlite3`。

US-003 已落地的预测边界：`backend/domain/predictions.py` 归一化答案、有序预测 chunk 和可选耗时，`backend/adapters/prediction_store.py` 保存不可变批次并绑定数据集版本。同文件建集与预测写入共用 SQLite 事务。`backend/api/predictions.py` 提供导入、列表与分页预览；文件适配器不调用被测 RAG。React 预测批次页显示匹配与未匹配数量和逐题内容。

US-005/006 已落地的本地匹配边界：`backend/adapters/local_embeddings.py` 使用 FastEmbed ONNX 模型下载/离线加载，并以权重内容指纹及正文键缓存向量；`backend/domain/matching.py` 仅在文档 ID 相同的参考/预测 chunk 之间生成余弦阈值候选。`backend/domain/retrieval_scoring.py` 对 Top-10/20 分别做最大命中数一对一归属，计算 Precision、AP、NDCG；预览接口和 React 预测详情展示候选与分数。

US-004 已落地的运行边界：`backend/adapters/run_store.py` 在 SQLite 中固定批次、模型、阈值及规则配置，逐题结果和错误分别保存；Huey Worker 在 `backend/worker/run_processor.py` 中逐题评分。API 可异步创建运行、查询列表/进度/样本、取消运行；React 运行页轮询状态。重复任务只允许一次从排队态领取，取消后不再写入新样本结果。

US-007 已落地的结果边界：运行聚合保存三项检索指标的均值与分布；逐题 API 支持状态筛选，CSV/JSON 导出从同一运行快照和逐题存储生成。React 运行页显示总体指标、逐题原文和匹配证据，空有效集显示不适用。

US-008 已落地的目标边界：`backend/adapters/http_target.py` 以通用 POST JSON 契约采集并校验结果，按尝试保存状态、耗时与可选 usage；`backend/adapters/target_store.py` 保存目标非敏感配置、采集任务及逐题结果，Bearer Token 单独放在仅本机可读的文件。Huey Worker 最多同时发出 4 个目标请求，完成后创建不可变预测批次。HTTP 失败记录在批次的尝试表，检索运行继承原始失败原因。React 目标页提供连接测试、数据集版本选择、采集启动及进度查看。

US-010/011 已落地的回答评分边界：场景三项评价标准按不可变版本保存；固定提示词骨架、变量和 JSON 输出契约由代码版本控制。在线 OpenAI 兼容模型配置与独立权限文件中的 Token 分开保存。运行选择检索、回答或组合模式，固定场景版本与非敏感模型参数快照。Worker 从同一不可变预测批次读取答案与上下文，分别保存每题每项指标的适用性、分数、原因、原始响应、usage 和错误；单项失败不覆盖其他指标。检索与回答聚合各用自己的有效样本分母，运行和逐题 API、CSV/JSON 导出、React 结果页读取同一持久化记录。

US-009 扩展目标协议为 SSE：`backend/adapters/sse_target.py` 使用 `httpx-sse` 解析事件，按 `answer.delta`、`contexts`、`completed`、`error` 组装结果。仅收到 `completed` 且满足评测类型必需字段才保存成功预测；逐次尝试记录 TTFT、TTLT 与流完成耗时，断流和流内错误由有限重试处理。目标配置固定 JSON 或 SSE 模式，二者输出同一规范化预测结构。

文档集合使用 `backend/domain/document_collections.py` 校验 TXT/Markdown、ID 与切块参数，`backend/adapters/document_store.py` 在一个 SQLite 事务中保存原始 BLOB、SHA-256 与有序切块。CSV/JSONL chunk 清单由 `backend/domain/chunk_manifests.py` 校验全局顺序、文档 ID、正文与重复项，同样原子保存。集合以 `source_kind` 区分 `original_files` 和 `chunks_only`；后者没有文件名、校验值、原始字节或下载 URL。管理 API 提供创建、清单导入、列表和详情，详情的 `chunks` 保留可供后续生成流程使用的全局顺序。原始字节仅存于业务库，独立下载入口由 US-016 实现。

US-017 的生成边界：`backend/domain/generation.py` 按固定顺序分配单/多 chunk 配额与来源；`backend/adapters/generation_model.py` 调用在线 OpenAI 兼容模型，要求结果只引用本次提供的 chunk 位置；`backend/adapters/generation_store.py` 原子保存任务、尝试和只读待审核候选。Huey Worker 以任务状态原子领取防止重复执行，最多 4 个并发模型请求，受任务最大调用次数约束。失败响应只保存诊断代码，合格候选仍可查看；模型凭据沿用受保护的在线模型配置，不进入任务快照。US-018 接续候选审核与编辑。

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

US-022 落地：`backend/tracing.py` 配置 OTLP HTTP 异步导出并限制属性白名单；`backend/adapters/trace_store.py` 在业务 SQLite 中保存关联 ID、span ID 和生成时间，不保存 trace 正文。Huey 消息携带 W3C `traceparent`，线程池复制当前上下文。导入、生成、目标采集和评测各自埋点；目标预测批次与后续评测分别保留 trace 链接。`RAGEVA_TRACE_RETENTION_DAYS` 只计算页面过期提示，Jaeger 存储需配置相同保留期，详见 [trace 配置](tracing.md)。

- `POST /api/v1/datasets/import`，`GET /api/v1/datasets/{id}/versions`
- `POST /api/v1/document-collections`：上传 TXT/Markdown/DOCX/文本 PDF 或导入已有 chunk 清单；原文提取、切块与 `document_id` 校验后形成不可变快照。
- `POST /api/v1/document-collections/{id}/generations`，`GET /api/v1/generations/{id}`，`GET /api/v1/generations/{id}/candidates`：生成任务接收目标条数、多 chunk 比例、语言、题型和补充要求，返回进度、实际数量和不足原因；完整 token 用量汇总由 US-021 接入。
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
