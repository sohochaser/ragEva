# 自动化测试案例说明

本文面向使用 ragEva 的人，说明当前自动化测试验证了什么、怎样判断结果，以及哪些结论不能从测试推出。内容基于 2026-10-02 的已实现版本（提交 `5103f2c`，用户故事 US-001 至 US-023）。测试代码是具体输入和断言的最终依据；[用户故事](stories.md)记录功能的验收目标。

## 先看测试结果

统一检查命令为 `make check`。最近一次已记录的完整检查通过：后端 pytest 123 项、前端 Vitest 27 项、浏览器 Playwright 1 项；[千题容量记录](performance.md)另记录了 1,000 题测试通过。这里的数量是测试项数，不是功能覆盖率或线上成功率。本次文档整理没有重新运行完整检查。

| 检查层 | 主要验证内容 | 失败时先看什么 |
| --- | --- | --- |
| 后端测试 | 导入、版本快照、评分、任务状态、错误处理、安全边界与容量 | 失败案例的输入、期望值和对应业务规则 |
| API 契约检查 | OpenAPI 与生成的前端类型保持一致 | 接口字段是否变动、生成文件是否同步 |
| 前端组件测试 | 页面输入、状态展示、交互和错误提示 | 页面是否正确呈现后端状态，操作是否触发预期请求 |
| 浏览器关键路径 | 在真实浏览器中串起前端、API、Worker 和下载进程 | 哪一步未完成、浏览器截图和 trace、服务日志 |

首次在本机运行需按 [README](../README.md#本机运行) 执行 `make setup`；浏览器测试还需要 Chromium（macOS 可使用已安装的 Chrome）。`make check` 也会执行代码格式、静态检查、类型检查和前端生产构建，因此其失败不一定表示某个业务案例失败。

## 案例索引

以下“通过”是测试应核对的结果，不代表当前连接的真实模型或 RAG 服务也已接受测试。每组至少列出一个可追溯的测试文件。

| 案例 | 对应故事 | 用户操作或测试输入 | 通过时应看到什么 | 主要测试 |
| --- | --- | --- | --- | --- |
| AT-01 启动与健康检查 | US-001 | 启动 API 与 Worker，查询存活和就绪状态；输入无效配置 | 存活接口可区分 API 状态；Worker 不可用时就绪接口返回 503；无效配置被拒绝 | [健康检查](../backend/tests/test_health.py)、[进程联动](../backend/tests/test_processes.py)、[配置](../backend/tests/test_config.py) |
| AT-02 金标准导入与版本 | US-002 | 上传 CSV/JSONL，映射字段，导入新版本；混入错误行 | 样本和参考 chunk 顺序正确；旧版本不变；错误定位到行/字段，失败文件不留下半个版本 | [金标准导入](../backend/tests/test_datasets.py)、[数据集页面](../frontend/src/datasets/DatasetPage.test.tsx) |
| AT-03 预测批次导入 | US-003 | 导入已有数据集的答案/检索结果，或同文件创建金标准与预测 | `case_id` 匹配、预测顺序和数据集版本绑定正确；无效文件整批拒绝 | [预测导入](../backend/tests/test_predictions.py)、[预测页面](../frontend/src/predictions/PredictionPage.test.tsx) |
| AT-04 运行、取消与导出 | US-004、US-007 | 创建异步评测、查询进度/逐题结果、取消、导出 JSON/CSV | 任务状态与处理数一致；取消和失败有明确终态；导出数量及逐题标识与结果一致 | [运行](../backend/tests/test_runs.py)、[运行页面](../frontend/src/runs/RunPage.test.tsx)、[恢复](../backend/tests/test_recovery.py) |
| AT-05 本地匹配与检索评分 | US-005、US-006 | 比较参考/预测 chunk，相似度过阈值后计算 Precision、AP/MAP、NDCG | 一对一匹配；跨文档、低于阈值及重复命中不能虚增分数；排序改变按规则影响 NDCG | [匹配](../backend/tests/test_matching.py)、[检索评分](../backend/tests/test_retrieval_scoring.py)、[匹配预览](../frontend/src/predictions/MatchingPreview.test.tsx) |
| AT-06 JSON/SSE 目标采集 | US-008、US-009 | 配置 HTTP 目标、试连、批量采集，注入 429/超时/错误 | 答案和有序上下文解析正确；SSE 计时/用量按响应记录；失败、重试和并发上限可见 | [JSON 目标](../backend/tests/test_http_target.py)、[SSE 目标](../backend/tests/test_sse_target.py)、[采集任务](../backend/tests/test_targets.py) |
| AT-07 场景、回答评分与复评 | US-010 至 US-012 | 保存评分标准，运行忠实度/相关性/正确性评分，调整配置后复评 | 场景快照固定；有效分数、评分失败和不适用分开统计；复评沿用已有预测，不重复采集目标 | [场景](../backend/tests/test_scenarios.py)、[回答评分](../backend/tests/test_answer_runs.py)、[复评](../backend/tests/test_rescore.py) |
| AT-08 原文与 chunk 集合 | US-013 至 US-015 | 上传 TXT/Markdown、DOCX、文本 PDF；或导入 CSV/JSONL chunk 清单 | 原始字节、哈希、文档 ID 与切块顺序固定；无效文件/清单整批拒绝；纯 chunk 集合标明无原文 | [原文集合](../backend/tests/test_document_collections.py)、[chunk 清单](../backend/tests/test_chunk_manifests.py) |
| AT-09 独立原文下载 | US-016 | 使用或省略专用 Bearer Token 获取清单和原文件 | 只有有效 Token 可以访问；文件字节和 SHA-256 对应上传原件；纯 chunk 集合没有文件下载地址 | [下载服务](../backend/tests/test_download.py) |
| AT-10 候选生成配额 | US-017 | 设定目标数量、多 chunk 比例、语言和题型；令来源不足或模型出错 | 只生成有足够来源的候选；保留实际/目标数和不足额原因；失败受调用预算限制 | [生成任务](../backend/tests/test_generations.py)、[生成页面](../frontend/src/generations/GenerationPage.test.tsx) |
| AT-11 审核、查重与发布 | US-018 至 US-020 | 编辑答案/参考 chunk、批准、处理重复、发布到新/旧数据集 | 审核修订可追溯；确定重复阻止发布；疑似重复需理由且修改后重新检查；发布创建不可变版本，失败不产生半成品 | [审核](../backend/tests/test_candidate_review.py)、[查重](../backend/tests/test_candidate_duplicates.py)、[发布](../backend/tests/test_candidate_publication.py) |
| AT-12 用量与 trace | US-021、US-022 | 运行调用模型/目标的任务，查看 Token 用量及 trace 链接，模拟链路服务不可用或过期 | 实际值、估算值、未知值不混用；敏感内容不写入 span；trace 不可用不遮蔽业务结果 | [模型用量](../backend/tests/test_model_usage.py)、[链路追踪](../backend/tests/test_tracing.py)、[trace 页面](../frontend/src/trace/TraceLink.test.tsx) |
| AT-13 千题、故障与恢复 | US-023 | 1,000 个混合样本注入目标 429/超时和评分超时；中断后重排、重复消息及取消 | 并发不超上限；所有题有终态；有效分母、导出行数和 `case_id` 唯一性正确；已保存评分不会重算 | [容量](../backend/tests/test_scale.py)、[恢复](../backend/tests/test_recovery.py) |
| AT-14 浏览器关键路径 | 跨 US-013 至 US-023 | 在真实浏览器完成上传、下载、生成、审核发布、目标采集、预测导入、评分、导出和复评 | 页面与服务之间的关键流程连通，并呈现候选不足额、疑似重复放行等状态 | [Playwright 用例](../frontend/e2e/critical-path.spec.ts) |

以下为 1.1 界面需求的自动化案例。AT-15 已落地；AT-16 在 US-029 中完成。

| 案例 | 对应故事 | 用户操作或测试输入 | 通过时应看到什么 | 拟落地的测试 |
| --- | --- | --- | --- | --- |
| AT-15 系统文案双语 | US-028 | 逐一打开八页，操作窄屏菜单、上传/导入弹窗、图标按钮，触发加载、空态与错误；提供中文文档名、问题和模型回答 | 系统自有可见文本、`title` 与可访问名称采用 `English（中文）`；英文和中文语义相同；用户内容及技术标识原样显示；320px 无整体溢出 | [导航与状态组件](../frontend/src/App.test.tsx)、[页面组件测试](../frontend/src/documents/DocumentCollectionPage.test.tsx)、[八页导航与宽度](../frontend/e2e/navigation.spec.ts)、[表单与弹窗](../frontend/e2e/surfaces.spec.ts)、[业务闭环](../frontend/e2e/critical-path.spec.ts) |
| AT-16 数值单位与大小 | US-029 | 上传时输入切块 1000、重叠 100，查看精确文件字节数；检查目标超时 30 秒、耗时 20 毫秒、token 用量、30% 比例、0.8 阈值及缺失值 | 每个输入/读数旁有正确双语单位或无单位范围；原始提交值分别仍为 1000、100、30、0.3、0.8；未知不写成 0；窄屏不截断标签 | 扩充文档/生成/目标/运行页面组件测试及 `frontend/e2e/surfaces.spec.ts` |

## 几个容易误读的结果

**导入失败并非“导入了一部分”。** 金标准、预测批次和文档集合测试都会混入错误数据，核对错误定位与事务结果。若文件有无效行，应看到错误提示，且不新增半成品数据集版本或批次。已有版本仍能读取。

**检索分数按一对一命中计算。** [检索评分用例](../backend/tests/test_retrieval_scoring.py)中，两条参考 chunk 只被一条预测命中时，`Precision@10 = 0.1`、`AP@10 = 0.5`。复制同一预测不会多算一次命中；不同文档或低于阈值的候选不算命中。`MAP` 的汇总分母只包括适用的样本，故不能仅看总题数解释均值。

**零分、失败、不适用是三种不同情况。** 真实返回的 `0` 是有效分数；模型超时或返回超出范围的分数会标为失败且没有可用分数；缺少回答或上下文时，相应指标可能不适用。汇总时只用有效分数计算均值，同时分别显示失败与不适用数量。[回答评分测试](../backend/tests/test_answer_runs.py)覆盖这些分支。

**候选不足额仍可能有可审核结果。** 浏览器用例要求生成 2 条，但来源只有一条可用 chunk，因此页面显示 `候选 1/2` 和不足额原因；已生成的 1 条仍可审核、批准和发布。这个结果表示配额未满足，不表示整个生成过程没有产出。

**部分故障不是“全部成功”。** 千题测试有意注入超时与 429。它要求每题落到明确终态、失败数与实际注入一致，并使有效分母和导出仍正确。因此该测试通过时，整体任务也可能显示失败状态，这是预期的故障处理结果。恢复测试另外验证中断后已保存的评分不会重复调用。

**用量与 trace 只说明可观测性。** 用量显示需区分模型返回的实际 Token、系统估算、未知和不适用；不能把未知当作零。trace 过期或 Jaeger 不可用时，业务结果仍应可查；span 不应包含问题、chunk 正文、Token 或错误正文。详见[全链路 trace 说明](tracing.md)。

## 浏览器与容量测试的边界

Playwright 用例会启动隔离的 API、Worker、下载服务及本地确定性模型/RAG 替身，在真实浏览器中检查一条跨功能路径。它检验页面和服务集成，但不评价真实第三方模型回答质量，也不验证外部 RAG 的部署与密钥。其余页面分支主要由组件和后端测试覆盖，不应把 1 项浏览器用例解读为所有界面操作都已逐一实测。

千题用例使用本地模拟响应，断言耗时小于 600 秒。[容量记录](performance.md)中的本机 3.78 秒和浏览器 16.3 秒是特定机器、特定替身服务上的一次结果，不是生产环境吞吐或响应时间承诺。扫描版 PDF 的 OCR 也不在当前产品能力和自动化测试范围内。

## 复现与定位

在项目根目录执行 `make check` 可复现统一门槛。需要定位某一层时，可以运行 `make backend-check`、`make contract-check`、`make frontend-check` 或 `make e2e-check`。单独运行千题案例可用 `uv run --frozen pytest -q -s backend/tests/test_scale.py`。浏览器失败时，先查看 Playwright 保留的截图和 trace，再核对对应服务日志；后端失败时，依据上表的测试文件查具体断言和输入。
