# 通用 JSON HTTP 目标（US-008）

在“HTTP 目标”页配置名称、POST URL、可选 Bearer Token、超时与重试次数。接口要求请求体 `{"case_id":"...","question":"..."}`，响应是含 `answer` 和/或按顺序排列的 `contexts` 的 JSON 对象；每个 context 要有 `text` 与 `document_id`。评测类型决定必需字段。目标可返回 `usage.input_tokens` 和 `usage.output_tokens`；缺失时不估算其内部用量。连接测试可先发送一题，显示成功或错误与尝试次数。

目标可选 JSON 或 SSE 响应协议。SSE 请求在上述 JSON 请求体中增加 `"stream": true`；事件为 `answer.delta`（`{"text":"..."}`）、`contexts`（`{"items":[...]}`）、`completed`（可含 `usage`）或 `error`（`code`、`message`）。上下文可先于或晚于回答增量；心跳和空增量不产生回答计时。只有 `completed` 到达且必需字段齐全，流式预测才记为成功；流内错误、断流或缺少结束事件保留尝试错误。流事件由 [httpx-sse](https://github.com/florimondmanca/httpx-sse) 解析。

每次 SSE 尝试记录从请求发起到首个非空答案增量的 TTFT、最后一个非空答案增量的 TTLT，以及到 `completed` 的完成耗时。失败尝试没有完成耗时；没有答案增量时 TTFT/TTLT 为空。重试后的预测总耗时包含所有尝试，文件预测的目标调用耗时仍为空。

采集任务绑定目标和不可变数据集版本，通过 Worker 异步处理，每个任务最多 4 个并发请求。超时、连接错误、429 和指定 5xx 会按配置重试；401、其他 4xx、无效 JSON、缺失业务字段不会重试。逐题保存每次尝试状态、HTTP 状态、耗时、usage 和错误。完成后即使部分题失败，也会创建不可变预测批次；成功题与文件导入共享规范化预测结构，失败原因被后续评测运行继承。

管理 API 为 `POST/GET /api/v1/targets`、`POST /api/v1/targets/{id}/test`、`POST/GET /api/v1/target-jobs`、`GET /api/v1/target-jobs/{id}` 与 `GET /api/v1/target-jobs/{id}/cases`。目标 Token 存储在数据目录 `secrets/targets/` 的私有文件中，不出现在列表、任务、运行结果或导出中。目标 URL 不能嵌入账号密码或常见凭据查询参数。
