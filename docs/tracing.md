# 全链路 trace

US-022 使用 OpenTelemetry 生成 trace，并以 OTLP HTTP 发送到 Jaeger 或兼容的 Collector。API 创建运行、生成任务和目标采集任务时，将 W3C `traceparent` 放进 Huey 消息；Worker 恢复上下文后记录任务、逐题、模型调用、chunk 匹配、重试尝试和结果落库 span。文件导入和文档集合导入也记录独立 span。目标采集形成的预测批次与后续评测运行可能属于两个 trace，运行结果页分别提供运行、预测批次和数据集版本入口，逐题页关联目标调用与评分；生成结果页关联来源集合。

启动 API 和 Worker 前设置：

```sh
export RAGEVA_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
export RAGEVA_JAEGER_URL=http://127.0.0.1:16686
export RAGEVA_TRACE_RETENTION_DAYS=30
make dev
```

前两个地址分别是 OTLP HTTP traces 接收端和浏览器可访问的 Jaeger UI 基础地址。未同时配置时，任务仍生成并保存 trace ID，但界面显示“Jaeger 未配置”。导出采用后台批量发送；Jaeger/Collector 停机不会阻断导入、采集、生成或评分。界面不探测 Jaeger 的实时可用性。

`RAGEVA_TRACE_RETENTION_DAYS` 默认为 30，只用于计算链接的预计过期时间；需在 Jaeger 存储后端设置相同保留期。达到该时间后界面显示“Trace 已过期”并隐藏链接。业务数据库中的问题、答案、chunk、评分依据、原始模型响应和逐题错误仍可查看，直至用户删除相应记录。更改保留期会按新配置重算现有 trace 的提示。

trace 属性限定为关联 ID、模型标识、状态、计数、耗时、token 用量、受控错误码和异常类型名。问题、chunk 正文、提示词、原始响应、URL、密钥、认证头及原始异常消息不会作为 span 属性或事件导出。业务记录中的 `trace_id` 和 `span_id` 与 Jaeger 对应；JSON/CSV 运行导出也包含逐题 trace 关联信息。

## 按请求查看本机日志

管理 API 的业务请求返回 `X-Request-ID`，值为 32 位 trace ID。System Status 的 Request Logs 展示最近 50 个请求，可筛选错误或输入请求 ID 精确查找。详情按开始时间展示已完成的 API、Worker、逐题、模型调用与落库步骤，包含耗时、状态和允许的关联元数据。异步任务运行中可刷新详情；Worker 步骤会随执行进度出现。也可用 `GET /api/v1/request-logs` 和 `GET /api/v1/request-logs/{request_id}` 查询。

请求日志存在本机业务 SQLite，不需要配置 Jaeger，也不受 Jaeger 30 天保留期影响。日志只记录白名单 span 属性和受控错误码、异常类型、通用错误说明；不保存请求/响应正文、原始异常消息、目标 URL、凭据或认证头。详细问题、响应与评分依据仍在相应业务记录中。启用此功能之前的 trace 无法回填步骤日志；健康探测及日志查询请求不加入近期业务请求列表。
