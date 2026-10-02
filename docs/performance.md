# US-023 容量与故障验证

`backend/tests/test_scale.py` 使用 1,000 个混合标注样本、固定 JSON 目标、固定在线评分模型和本地向量桩，注入 HTTP 429、目标超时和评分模型超时。测试核对采集并发上限、所有题目的终态、各指标有效分母、JSON/CSV 导出数量及无重复 `case_id`，并断言总耗时小于 600 秒。所有外部请求都指向内存中的确定性桩。

2026-10-02 本机记录：Python 3.11.14，macOS 26.6.2 arm64，1,000 题全流程耗时 3.78 秒。命令：`uv run --frozen pytest -q -s backend/tests/test_scale.py`。`backend/tests/test_recovery.py` 另覆盖中断后重排、已保存评分复用、重复消息、排队与运行中取消。

`frontend/e2e/critical-path.spec.ts` 在真实 Chrome、隔离的管理 API、Worker、下载进程及确定性模型/RAG 桩上验证原文上传、Token 下载、候选不足额、审核发布、疑似重复放行、JSON/SSE 目标采集、文件预测导入、回答评分、复评和 JSON 导出。2026-10-02 本机 Chrome 运行 1 项测试通过，耗时 16.3 秒；命令为 `npm --prefix frontend run test:e2e`。测试服务在结束后正常退出，未使用真实密钥或外部模型。CI 安装 Playwright Chromium 并通过 `make check` 执行同一用例。
