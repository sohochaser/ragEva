# 系统架构草案

状态：架构草案。采用前后端分离的单仓库，一套 Python 后端和一个 React 前端通过版本化 HTTP API 通信。首版面向本机单人使用；API 进程与 Worker 使用同一套 Python 后端代码，分别承担交互请求和异步评测任务。

```text
React + TypeScript
    |
    | /api/v1 (JSON)
    v
Python API (FastAPI)
    |-- 数据集、目标配置、预测结果导入、运行、结果 API
    |-- 本机配置与密钥引用
    |
    +--> SQLite (数据集、预测结果、运行与评分)
    +--> SQLite 任务队列 --> Python Worker
                            |-- HTTP 调用或导入结果读取
                            |-- 统一预测结果模型
                            |-- chunk 语义匹配与检索指标
                            |-- LLM 指标适配器
                            +-- 运行结果与调用轨迹
```

## 组件边界

- `frontend/`：React + TypeScript。数据集、输入方式、系统连接、预测结果导入、场景评价标准配置、运行、总体与逐样本结果视图；不持有第三方 API 密钥。
- `backend/api/`：FastAPI、输入校验和契约序列化；不直接执行长评测任务。
- `backend/domain/`：数据集版本、指标输入输出、运行状态机与结果聚合规则；不依赖 Web、数据库或队列框架。
- `backend/adapters/`：目标 RAG HTTP 协议、CSV/JSONL 预测结果导入、评测模型和持久化实现。HTTP 与文件适配器产出同一预测结果模型。
- `backend/worker/`：样本调度、限流、重试、取消和结果落库。队列实现可替换；初版选成熟组件，避免自制任务系统。
- `contracts/`：OpenAPI 和可共享的示例请求、响应；前端类型由契约生成。

依赖方向：API/Worker -> 领域服务 -> 端口接口；适配器实现端口。前端只依赖公开 API 契约。

## 核心实体

`Dataset`、`DatasetVersion`、`EvaluationCase`、`TargetConfig`、`PredictionBatch`、`Prediction`、`MetricConfig`、`EvaluationScenario`、`EvaluationRun`、`ChunkMatchDecision`、`CaseResult`、`MetricResult`。HTTP 调用和文件导入都生成不可变 `PredictionBatch`，评分运行引用该批次。一个场景包含三项回答指标可编辑的评价标准；系统提示词结构和输出格式由代码版本控制。运行选择一个场景，并保存数据集版本、预测批次及来源快照、指标配置与版本、场景标准及系统提示词版本快照、评测模型地址、名称和非敏感参数、开始/结束时间和状态。逐样本保留答案、检索片段引用、耗时、评分、错误与证据。`ChunkMatchDecision` 保存参考与预测 chunk、判定理由、模型和规则版本，供复评与审查复用。密钥只保存受保护的引用，不进入导出文件。

规范化样本有 `case_id` 和 `question`。端到端答案样本携带 `reference_answer`；检索样本携带有序 `reference_chunks`；同一题可以同时带两类标注，也可只带其中一种。每个参考 chunk 记录正文和所属 `document_id`，列表位置即从高到低的参考相关性顺序；不要求共享 chunk ID 或数值相关性分数。规范化预测包含 `case_id`，以及按评测类型提供的 `answer` 和按预测检索顺序排列的 `contexts`；检索评测必须有 `contexts`，答案评测必须有 `answer`，需要计算忠实度时还必须有 `contexts`。每个预测 chunk 包含正文和 `document_id`，可附带片段 ID、来源及耗时。HTTP 与文件适配器都输出这一结构。检索匹配先用文档 ID 限定候选，再判断对问题的关键证据是否由预测 chunk 保留；文档 ID 相同不能直接算命中。

## 运行状态与一致性

运行状态为 `queued -> running -> completed | failed | cancelled`。每个样本有独立状态；重复投递以运行 ID + 样本 ID 幂等写入。仅成功完成的样本计入相应指标聚合，报告必须同时显示有效样本数、失败数和不适用数。

## API 草案

被测 RAG 服务的首版通用契约为 `POST {target_url}`，请求 JSON 为 `{"case_id": "...", "question": "..."}`，典型响应 JSON 为 `{"answer": "...", "contexts": [{"document_id": "...", "text": "...", "chunk_id": "...", "source": "..."}]}`。`answer` 和 `contexts` 按评测类型校验；检索评测必须有 `contexts`，回答评测必须有 `answer`，忠实度还需要 `contexts`。`contexts` 顺序即预测检索排序，每个 chunk 的 `document_id` 与 `text` 必填，`chunk_id`、`source` 可选。连接测试校验该契约，调用耗时由评测系统测量。后续真实系统协议通过适配器转换到规范化预测模型。

- `POST /api/v1/datasets/import`，`GET /api/v1/datasets/{id}/versions`
- `POST /api/v1/targets`，`POST /api/v1/targets/{id}/test`
- `POST /api/v1/predictions/import`，`GET /api/v1/predictions/{id}`
- `GET /api/v1/scenarios`，`POST /api/v1/scenarios`，`PUT /api/v1/scenarios/{id}`，`POST /api/v1/scenarios/{id}/preview`
- `POST /api/v1/runs`，`GET /api/v1/runs/{id}`，`POST /api/v1/runs/{id}/cancel`
- `POST /api/v1/runs/{id}/rescore`：复用原运行的预测批次，使用所选场景模板创建新评分运行。
- `GET /api/v1/runs/{id}/results`，`GET /api/v1/runs/{id}/export`

接口路径是设计草案；实现前用 OpenAPI 样例和契约测试固定字段、错误码及分页规则。

## 技术取舍

首版使用 SQLite 保存本机数据，并使用 Huey 的 SQLite 队列驱动独立 Python Worker，无需单独运行 PostgreSQL 或 Redis。用户数据保存在可配置的本机目录，默认仅绑定 `127.0.0.1`。评测模型适配器调用用户配置的 OpenAI 兼容 API 地址、模型名与凭据；Ragas 等现有评测库承接回答指标，并在本项目适配层固定指标版本与提示词。检索指标在可审查的语义匹配判定之上按明确定义计算，匹配判定按数据集、预测内容与评测配置缓存。所有外部模型调用都可替换为测试桩，以便 CI 不依赖付费服务。
