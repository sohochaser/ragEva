# 检索评测运行（US-004、US-006）

在“评测运行”中选择已导入的检索或混合预测批次，填写本地向量模型及阈值，启动后由 Huey Worker 逐题评分。API 创建请求立即返回 `queued`；页面每两秒读取运行及逐题状态。取消排队任务会将待处理题标为 `cancelled`；运行中取消会保留已完成题，停止写入新题结果。

`POST /api/v1/runs` 接收 `prediction_batch_id`、`model_name`、可选 `model_path`、`offline`、`threshold` 和指标列表。`GET /api/v1/runs`、`GET /api/v1/runs/{id}`、`GET /api/v1/runs/{id}/cases` 提供历史与分页逐题结果；`POST /api/v1/runs/{id}/cancel` 请求取消。Worker 不可用返回 503；批次不存在返回 404；答案专用批次不能运行检索指标，返回 422。

运行快照绑定数据集版本、预测批次、模型名称/权重指纹、阈值与规则版本。逐题分数保存 K=10/20 的候选边判定和最终配对；失败题不参与均值，只有答案标注而无参考 chunk 的题计为不适用。重复消费同一任务不会覆盖已保存结果。当前运行页展示进度和逐题状态；完整分数详情、分布和导出属于 US-007。
