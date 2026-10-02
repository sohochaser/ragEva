# 预测文件导入格式（US-003）

上传 UTF-8 `.csv` 或 `.jsonl`。每行有 `case_id`，并按选择的评测类型提供 `answer`、`contexts` 或两者。`contexts` 是按被测系统检索顺序排列的非空数组，每项必须有 `text` 与 `document_id`，可选 `chunk_id`、`source`。可选 `latency_ms` 是非负毫秒数；文件预测不填写时表示没有目标调用耗时。CSV 中 `contexts` 与 `reference_chunks` 单元格使用 JSON 数组文本。支持顶层字段映射，chunk 内字段名固定。

匹配已有数据集时指定数据集与版本；未指定版本时采用导入开始时的最新版本。未知或重复的 `case_id`、缺少所选类型要求的预测字段、无效 chunk、坏文件会返回行号与原因，整批不落库。数据集里未出现在预测文件中的题目允许存在，记入 `missing_case_count`。`matched_count` 是成功匹配的预测记录数。导入不会请求被测 RAG 服务。

JSONL 预测文件示例：

```jsonl
{"case_id":"q-1","answer":"答案 A","contexts":[{"text":"第一段","document_id":"doc-1"},{"text":"第二段","document_id":"doc-2"}]}
{"case_id":"q-2","answer":"答案 B","contexts":[{"text":"依据","document_id":"doc-2"}],"latency_ms":31.5}
```

选择“同文件新建”时，文件还必须包含金标准字段 `question`，以及 `reference_answer` 或有序 `reference_chunks`；字段含义与校验规则见[金标准格式](dataset-format.md)。金标准数据集首版与预测批次在同一 SQLite 事务中创建，任一行无效则两者都不创建。例如：

```jsonl
{"case_id":"q-1","question":"问题是什么？","reference_answer":"标准答案","answer":"预测答案","contexts":[{"text":"检索片段","document_id":"doc-1"}]}
```

每个预测批次绑定创建时的数据集版本；后续导入新金标准版本不会改变历史批次。批次和样本只读，供后续评测运行引用。
