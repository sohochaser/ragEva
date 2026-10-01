# 金标准数据集导入格式（US-002）

上传 `.csv` 或 `.jsonl` UTF-8 文件。每行是一道单轮问题；`case_id` 和 `question` 必填，`reference_answer` 与 `reference_chunks` 至少有一个。`reference_chunks` 若出现，必须是非空数组；数组顺序就是参考 chunk 从高到低的相关性顺序。每个 chunk 必须有 `text` 和 `document_id`。同一文档内正文去首尾空白并合并连续空白后相同的参考 chunk 不允许重复。

JSONL 每行是一个 JSON 对象，例：

```jsonl
{"case_id":"q-1","question":"什么是 RAG？","reference_answer":"检索增强生成。"}
{"case_id":"q-2","question":"文档讨论了什么？","reference_chunks":[{"text":"第一段","document_id":"doc-1"},{"text":"第二段","document_id":"doc-1"}]}
{"case_id":"q-3","question":"如何评测？","reference_answer":"检查检索与回答。","reference_chunks":[{"text":"评测说明","document_id":"doc-2"}]}
```

CSV 的 `reference_chunks` 单元格是 JSON 数组文本，空单元格表示没有此类标注，例：

```csv
case_id,question,reference_answer,reference_chunks
q-1,什么是 RAG？,检索增强生成。,
q-2,文档讨论了什么？,,"[{""text"":""第一段"",""document_id"":""doc-1""}]"
```

上传时可将四个顶层字段映射到文件中的其他列名或键名；chunk 内的 `text` 和 `document_id` 不映射。CSV 的首行是表头。行号按文件中的记录顺序返回，CSV 首条数据为第 2 行；JSONL 使用实际物理行号。任何一行不合法，整次导入失败，不生成数据集或版本。

新建数据集需要名称。导入到已有数据集时，文件表示**完整的新版本快照**，不是追加记录；可沿用旧版 `case_id` 并更新标注。每个版本保存导入后的规范化样本、参考顺序、来源文件名和创建时间。旧版本始终可读，MVP 不提供修改或删除版本的接口。
