# 分析框架 API（已实现）

基础路径`/api/v1/analysis`，Bearer认证，首次改密规则沿用公共接口。catalog对已登录用户可见；批次的创建/查询/推进/事件/重试均仅允许当前任课教师。学生不能查询通用结果。ID字符串、UTC时间、十进制分数字符串、统一错误格式。

| 方法 / 相对路径 | 输入 | 行为 |
|---|---|---|
| GET /catalog | 无 | 15插件及输入/输出JSON Schema、实现名/版本、是否有演示实现 |
| POST /courses/{course_id}/batches | 下述创建DTO | 201；保存ROOT快照和23步骤，独立步骤置READY；不在HTTP内执行算法 |
| GET /batches/{batch_id} | 无 | 各任务状态、依赖、阻塞原因、attempt、完成结果；不返回原始ROOT内容 |
| POST /batches/{batch_id}/run | `{request_id}` | 重新检查依赖，只将可执行任务置READY，不越过人工节点 |
| POST /batches/{batch_id}/demo-events | 下述事件DTO | 仅DEMO；固定合成fixture推进人工步骤，不接受真实评分数据 |
| POST /batches/{batch_id}/runs/{run_id}/retry | `{request_id}` | 仅FAILED、有输入快照、总尝试小于3；不改变输入或实现版本 |

创建示例：

```json
{"mode":"DEMO","seed":20261026,"request_id":"meeting-demo-001"}
```

REAL_INPUT支持可选字符串`assignment_id`、`assignment_item_id`，均须属于当前课程；指定item时先解析所属作业，再读取其固定应交名单、提交、事件和评测摘要，不混入其他题。未指定item的多题快照仍可做整体行为统计，要求单题范围的算法明确等待SINGLE_ITEM_SCOPE_REQUIRED。

DEMO总是六名合成学生/编程与主观两类题，真实作业身份不进入合成fixture。所有派生输出is_mock=true，。真实模式读取当前执行上下文中的非mock评测候选，缺互评/量表/发布适配就等待；插件未实现时返回NOT_IMPLEMENTED，不自动用mock替代。

演示事件示例：

```json
{"event":"OPEN_REVIEW","request_id":"open-001","expected_version":0,"action":"KEEP"}
```

顺序：OPEN_REVIEW→SUBMIT_REVIEWS→RESOLVE。每次先运行worker并GET检查WAITING_HUMAN及revision_no。RESOLVE可选action=SUPPLEMENT，之后先等补充分配，再提交SUBMIT_SUPPLEMENT，再等重算与题目结果快照。评分、计时和决定全部来自合成样例，不接收任意原始评价字段。

创建幂等键为当前教师+request_id，包含课程及完整输入摘要；批次命令为当前教师+request_id，重用为不同操作返回409。完全相同事件重试不会重复写分；重试仍须使用原始请求正文（含原expected_version）。响应可返回当前批次视图，不保证回放旧JSON。

任务状态：WAITING_INPUT、WAITING_HUMAN、READY、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED。SUCCEEDED表示计算执行完毕，还要看business_status：OK、INSUFFICIENT_DATA、INFEASIBLE、NOT_IMPLEMENTED。后3种不自动满足需要有效分数或分配的下游。

阻塞原因含blocked_by/upstream_status或具体reason。冻结前的快照不会在后台自动更新，需关闭/截止后创建新批次。真实互评/教师处置/正式发布尚未接入领域服务，因此不能调用DEMO事件代替。

批次创建时固定全部算法实现名与版本，包括尚未就绪的任务；worker检查当前注册项是否仍一致，变更后旧批次记IMPLEMENTATION_CHANGED_CREATE_NEW_BATCH。失败重试输入不变，每次attempt使用新token和120秒租约；迟到结果拒收，过期任务需显式重试，不自动反复跑。

常见错误：401未登录；403非任课教师/首次改密；404跨课程或不存在；409 IDEMPOTENCY_CONFLICT、VERSION_CONFLICT、EVENT_NOT_READY、DEMO_ONLY、RETRY_NOT_ALLOWED、WRITE_CONFLICT；422未知字段/非法ID/seed、ANALYSIS_SCOPE_TOO_LARGE。ROOT快照上限8MiB、每批最多100个幂等命令。

第六条线可独立运行：只调用现有ability占位黑盒，不等待其他线路。见[独立线路说明](student-ability-line.md)。

## 相似代码检测与复杂度分析接口（2026-10-28 已实现）

两族接口都挂在 `/api/v1/analysis` 下，沿用 Bearer 认证、字符串 ID、统一错误格式。相似检测仅教师可用；复杂度报告学生只能读自己的、教师可读本课程。

| 方法 / 相对路径 | 权限 | 行为 |
|---|---|---|
| GET /courses/{course_id}/code-similarity/scope | 教师 | 可选作业范围：每题有多少人已提交，用于决定比对哪道题 |
| POST /courses/{course_id}/code-similarity/batches | 教师 | 201；创建 `pipeline=CODE_SIMILARITY` 批次，每题一个 `code_similarity@<item_id>` 任务；不等待计算完成 |
| GET /batches/{batch_id}/similarity | 教师 | 相似证据：配对、行号区间、相似簇、未参与比较的提交及原因；补学号与姓名 |
| POST /submissions/{submission_id}/complexity | 本人 / 本课程教师 | 202；已存在报告时直接返回，不重跑；不合格返回 409 并说明原因 |
| GET /submissions/{submission_id}/complexity | 本人 / 本课程教师 | 报告，或 `status=NONE` 表示尚未请求 |
| GET /courses/{course_id}/complexity | 教师 | 班级概览：每生每题最新一份报告的类别、置信度与来源（执行轨迹） |
| POST /courses/{course_id}/complexity/batch | 教师 | 202；为该题全部真实通过的提交排队分析，已有报告的跳过；返回 `queued`/`skipped`/`ineligible` 与不合格原因分布 |
| GET /courses/{course_id}/complexity/items | 教师 | 哪些编程题配置了规模伸缩档 |

创建相似批次示例：

```json
{"request_id":"sim-001","assignment_id":"1","assignment_item_id":"1","threshold":"0.5"}
```

`assignment_item_id` 省略时比较该作业全部编程题，但每道题仍然独立成组，绝不跨题配对。

相似证据返回里每条配对带双方记号数（`left_tokens`/`right_tokens`），教师端据此标注弱证据；每个簇带 `qualifying_pairs`/`total_pairs`/`min_similarity`，教师端据此区分“团”与“链”；每题带 `language_counts`，混语言时提示跨语言不可比。


复杂度资格（任一不满足即 409）：`SUBMISSION_WITHDRAWN`、`NOT_A_PROGRAMMING_ITEM`、`NOT_JUDGED_YET`、`MOCK_RESULT_NOT_ANALYSABLE`、`SUBMISSION_NOT_ACCEPTED`、`JUDGE_CONTEXT_CHANGED`、`JUDGE_CONFIGURATION_UNSUPPORTED`、`UNSUPPORTED_LANGUAGE`。

批次计算由 `python -m scripts.run_analysis --watch` 消费；复杂度轨迹采集由 `python -m scripts.run_complexity --watch` 消费，两者分开，采集不会拖慢评测。批次与报告都持久化，刷新页面看到的是同一份结果。复杂度报告的字段见 [complexity-trace.md](complexity-trace.md) 第 7 节：`time`/`space`/`trace`/`trace_meta`，状态包含 `NOT_MEASURABLE`（没有可伸缩输入或该语言没有轨迹采集器时明确说明原因）。
