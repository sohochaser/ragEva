# ragEva

本机单人使用的 RAG 评测系统：一套 Python 后端、React 前端；支持调用现有 RAG HTTP API 或导入已有预测结果。当前阶段：需求与架构草案，尚未开始产品代码实现。

- [产品需求](docs/requirements.md)
- [系统架构](docs/architecture.md)
- [开发与验收流程](docs/workflow.md)
- [任务拆解](docs/plan.md)
- [编号用户故事与验收清单](docs/stories.md)

MVP 需求草案见 `docs/requirements.md`；检索采用一对一 chunk 语义匹配，并按其中的验收场景推进。
