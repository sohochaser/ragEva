# 通用 JSON HTTP 目标（US-008）

在“HTTP 目标”页配置名称、POST URL、可选 Bearer Token、超时与重试次数。接口要求请求体 `{"case_id":"...","question":"..."}`，响应是含 `answer` 和/或按顺序排列的 `contexts` 的 JSON 对象；每个 context 要有 `text` 与 `document_id`。评测类型决定必需字段。目标可返回 `usage.input_tokens` 和 `usage.output_tokens`；缺失时不估算其内部用量。连接测试可先发送一题，显示成功或错误与尝试次数。

采集任务绑定目标和不可变数据集版本，通过 Worker 异步处理，每个任务最多 4 个并发请求。超时、连接错误、429 和指定 5xx 会按配置重试；401、其他 4xx、无效 JSON、缺失业务字段不会重试。逐题保存每次尝试状态、HTTP 状态、耗时、usage 和错误。完成后即使部分题失败，也会创建不可变预测批次；成功题与文件导入共享规范化预测结构，失败原因被后续评测运行继承。

管理 API 为 `POST/GET /api/v1/targets`、`POST /api/v1/targets/{id}/test`、`POST/GET /api/v1/target-jobs`、`GET /api/v1/target-jobs/{id}` 与 `GET /api/v1/target-jobs/{id}/cases`。目标 Token 存储在数据目录 `secrets/targets/` 的私有文件中，不出现在列表、任务、运行结果或导出中。目标 URL 不能嵌入账号密码或常见凭据查询参数。
