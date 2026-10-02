# US-023 容量与故障验证

`backend/tests/test_scale.py` 使用 1,000 个混合标注样本、固定 JSON 目标、固定在线评分模型和本地向量桩，注入 HTTP 429、目标超时和评分模型超时。测试核对采集并发上限、所有题目的终态、各指标有效分母、JSON/CSV 导出数量及无重复 `case_id`，并断言总耗时小于 600 秒。所有外部请求都指向内存中的确定性桩。

2026-10-02 本机记录：Python 3.11.14，macOS 26.6.2 arm64，1,000 题全流程耗时 3.78 秒。命令：`uv run --frozen pytest -q -s backend/tests/test_scale.py`。`backend/tests/test_recovery.py` 另覆盖中断后重排、已保存评分复用、重复消息、排队与运行中取消。

React 组件测试覆盖目标采集取消和运行结果关键状态。浏览器关键路径 E2E 尚未执行，US-023 的该项验收仍待完成。
