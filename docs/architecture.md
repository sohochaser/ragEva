# 系统架构草案

状态：待确认。采用前后端分离的单仓库，React 前端与 Python 后端通过版本化 HTTP API 通信。两个版本的具体含义确认后，再固定部署拓扑；评测领域模型和接口契约应保持一致。

```text
React + TypeScript
    |
    | /api/v1 (JSON)
    v
Python API (FastAPI)
    |-- 数据集、系统配置、运行、结果 API
    |-- 鉴权/授权与密钥引用
    |
    +--> PostgreSQL (元数据、样本、结果、审计)
    +--> 任务队列 --> Python Worker
                      |-- RAG HTTP 适配器
                      |-- 确定性检索指标
                      |-- LLM 指标适配器
                      +-- 运行结果与调用轨迹
```

## 组件边界

- `frontend/`：React + TypeScript。数据集、系统连接、运行、结果与比较视图；不持有第三方 API 密钥。
- `backend/api/`：FastAPI、输入校验和契约序列化；不直接执行长评测任务。
- `backend/domain/`：数据集版本、指标输入输出、运行状态机与比较规则；不依赖 Web、数据库或队列框架。
- `backend/adapters/`：目标 RAG HTTP 协议、评测模型和持久化实现。用接口隔离不同供应商与部署形态。
- `backend/worker/`：样本调度、限流、重试、取消和结果落库。队列实现可替换；初版选成熟组件，避免自制任务系统。
- `contracts/`：OpenAPI 和可共享的示例请求、响应；前端类型由契约生成。

依赖方向：API/Worker -> 领域服务 -> 端口接口；适配器实现端口。前端只依赖公开 API 契约。

## 核心实体

`Dataset`、`DatasetVersion`、`EvaluationCase`、`TargetConfig`、`MetricConfig`、`EvaluationRun`、`CaseResult`、`MetricResult`。运行保存数据集版本、目标配置快照、指标配置与版本、评测模型标识、开始/结束时间和状态；逐样本保留答案、检索片段引用、耗时、评分、错误与证据。密钥只保存受保护的引用，不进入导出文件。

## 运行状态与一致性

运行状态为 `queued -> running -> completed | failed | cancelled`。每个样本有独立状态；重复投递以运行 ID + 样本 ID 幂等写入。仅成功完成的样本计入相应指标聚合，报告必须同时显示有效样本数、失败数和不适用数。比较两个运行时，以稳定样本 ID 对齐，配置差异显式展示。

## API 草案

- `POST /api/v1/datasets/import`，`GET /api/v1/datasets/{id}/versions`
- `POST /api/v1/targets`，`POST /api/v1/targets/{id}/test`
- `POST /api/v1/runs`，`GET /api/v1/runs/{id}`，`POST /api/v1/runs/{id}/cancel`
- `GET /api/v1/runs/{id}/results`，`GET /api/v1/runs/compare`，`GET /api/v1/runs/{id}/export`

接口路径是设计草案；实现前用 OpenAPI 样例和契约测试固定字段、错误码及分页规则。

## 技术取舍

建议首版使用 PostgreSQL 保存可查询结果，成熟队列组件处理长任务，Ragas 等现有评测库承接 LLM 指标，并在本项目适配层固定指标版本与提示词。检索排序指标按明确定义实现并使用边界测试。所有外部模型调用都可替换为测试桩，以便 CI 不依赖付费服务。
