# 分析框架 API（已实现）

基础路径`/api/v1/analysis`，Bearer认证，首次改密规则沿用公共接口。catalog对已登录用户可见；批次的创建/查询/推进/事件/重试均仅允许当前任课教师。学生不能查询通用结果。ID字符串、UTC时间、十进制分数字符串、统一错误格式。

| 方法 / 相对路径 | 输入 | 行为 |
|---|---|---|
| GET /catalog | 无 | 15插件及输入/输出JSON Schema、实现名/版本、是否有演示实现 |
| POST /courses/{course_id}/batches | 下述创建DTO | 201；保存ROOT快照和24步骤，独立步骤置READY；不在HTTP内执行算法 |
| GET /batches/{batch_id} | 无 | 各任务状态、依赖、阻塞原因、attempt、完成结果；不返回原始ROOT内容 |
| POST /batches/{batch_id}/run | `{request_id}` | 重新检查依赖，只将可执行任务置READY，不越过人工节点 |
| POST /batches/{batch_id}/demo-events | 下述事件DTO | 仅DEMO；固定合成fixture推进人工步骤，不接受真实评分数据 |
| POST /batches/{batch_id}/runs/{run_id}/retry | `{request_id}` | 仅FAILED、有输入快照、总尝试小于3；不改变输入或实现版本 |

创建示例：

```json
{"mode":"DEMO","seed":20261026,"request_id":"meeting-demo-001"}
```

REAL_INPUT支持可选字符串`assignment_id`、`assignment_item_id`，均须属于当前课程；指定item时先解析所属作业，再读取其固定应交名单、提交、事件和评测摘要，不混入其他题。未指定item的多题快照仍可做整体行为统计，要求单题范围的算法明确等待SINGLE_ITEM_SCOPE_REQUIRED。

DEMO总是六名合成学生/编程与主观两类题，真实作业身份不进入合成fixture。所有派生输出is_mock=true，formal_grade_release=false。真实模式读取当前执行上下文中的非mock评测候选，缺互评/量表/发布适配就等待；插件未实现时返回NOT_IMPLEMENTED，不自动用mock替代。

演示事件示例：

```json
{"event":"OPEN_REVIEW","request_id":"open-001","expected_version":0,"action":"KEEP"}
```

顺序：OPEN_REVIEW→SUBMIT_REVIEWS→RESOLVE→RELEASE。每次先运行worker并GET检查WAITING_HUMAN及revision_no。RESOLVE可选action=SUPPLEMENT，之后先等补充分配，再提交SUBMIT_SUPPLEMENT，再等重算与RELEASE。评分、计时和决定全部来自合成样例，不接收任意原始评价字段。

创建幂等键为当前教师+request_id，包含课程及完整输入摘要；批次命令为当前教师+request_id，重用为不同操作返回409。完全相同事件重试不会重复写分；重试仍须使用原始请求正文（含原expected_version）。响应可返回当前批次视图，不保证回放旧JSON。

任务状态：WAITING_INPUT、WAITING_HUMAN、READY、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED。SUCCEEDED表示计算执行完毕，还要看business_status：OK、INSUFFICIENT_DATA、INFEASIBLE、NOT_IMPLEMENTED。后3种不自动满足需要有效分数或分配的下游。

阻塞原因含blocked_by/upstream_status或具体reason。冻结前的快照不会在后台自动更新，需关闭/截止后创建新批次。真实互评/教师处置/正式发布尚未接入领域服务，因此不能调用DEMO事件代替。

批次创建时固定全部算法实现名与版本，包括尚未就绪的任务；worker检查当前注册项是否仍一致，变更后旧批次记IMPLEMENTATION_CHANGED_CREATE_NEW_BATCH。失败重试输入不变，每次attempt使用新token和120秒租约；迟到结果拒收，过期任务需显式重试，不自动反复跑。

常见错误：401未登录；403非任课教师/首次改密；404跨课程或不存在；409 IDEMPOTENCY_CONFLICT、VERSION_CONFLICT、EVENT_NOT_READY、DEMO_ONLY、RETRY_NOT_ALLOWED、WRITE_CONFLICT；422未知字段/非法ID/seed、ANALYSIS_SCOPE_TOO_LARGE。ROOT快照上限8MiB、每批最多100个幂等命令。
