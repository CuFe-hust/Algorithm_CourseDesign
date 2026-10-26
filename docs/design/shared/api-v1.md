# 当前API格式 v1（已实现）

基础地址开发默认 `http://127.0.0.1:8000/api/v1`。本文件描述共享底座接口；[教师接口](../teacher/api.md) 单独列出；学生作答、历史与评测接口见第 7 节（2026-10-24 已实现）；尚未实现的远期提案见[下一阶段契约](../contracts/next-phase.md)。[OpenAPI快照](../contracts/openapi.json)可查参数和认证方式，交互文档为 `/docs`。

## 1. 统一格式

- 请求/响应JSON使用UTF-8，字段snake_case。教师名册上传使用 multipart/form-data。
- ID在JSON中是十进制字符串，前端不转Number；URL和查询参数按其字符串形式拼接。
- 时间为UTC ISO8601，例如 `2026-10-21T08:00:00+00:00`，页面转北京时间；分数/权重用字符串，例如 `100.00`、`0.250000`。
- 成功响应直接返回对象，没有统一data外壳。当前列表返回 `{items:[...]}`，教师提交、题库和学生列表增加total/limit/offset。
- 除health、ready、login外均需 `Authorization: Bearer <access_token>`。密码仅在认证请求body与教师专用一次性发放响应中传输，token不放URL或日志。空闲2小时失效、绝对24小时上限，401重新登录。
- 每个响应有X-Request-ID。错误格式如下，details通常为空，字段校验错误时是field/type数组。

```json
{
  "code": "SUBMISSION_CLOSED",
  "message": "作业未开放提交或已经截止",
  "details": null,
  "request_id": "示例请求编号"
}
```

| HTTP状态 | 含义 |
|---|---|
| 200 | 查询、登录、退出或撤回成功 |
| 202 | 正式提交已持久化；不代表评测已完成 |
| 401 | 未登录、token失效或账号不可用 |
| 403 | 有身份但明确不允许，如学生访问教师接口 |
| 404 | 资源不存在或当前身份不可见 |
| 409 | 截止、状态、配置或幂等内容冲突 |
| 422 | 字段、语言、内容大小等输入无效 |
| 500 / 503 | 内部故障 / 数据库或迁移尚未就绪，不泄露内部连接信息 |

前端用code处理分支，message用于展示，不能依赖中文文案逐字匹配。当前内部错误有请求编号，生产运维日志/监控后续补齐。

## 2. 健康与登录

### GET /health

公开，返回 `{"status":"ok"}`；不检查PostgreSQL。

### GET /ready

公开，数据库连接及迁移head一致返回 `{"status":"ready","migration":"pg0001"}`；旧/空/不识别的版本返回503。未来新增迁移后migration会改变，客户端不硬编码pg0001。

### POST /auth/login

请求字段：login_name字符串1～64字符，password字符串1～1024字符；禁止额外字段。登录名在后端去首尾空白并casefold，角色不由请求提供。

```json
{"login_name":"demo.student01","password":"<从本地.env读取的DEMO_PASSWORD>"}
```

```json
{
  "access_token": "<运行时返回的随机token>",
  "token_type": "bearer",
  "expires_in": 7200,
  "user": {"id":"11","login_name":"demo.student01","full_name":"演示同学"}
}
```

这是结构样例，不是可用密码/token或固定账号ID。login响应不含课程角色；登录后查询courses取得当前课程role。PENDING/DISABLED不能登录；错误密码401，不区分账号不存在。

### POST /auth/logout

需登录，无body要求；返回 `{"status":"logged_out"}`，当前会话作废。再次使用该token返回401。

## 3. 课程、作业与题目

### GET /courses

返回当前用户有效的课程成员关系，空列表合法，当前不分页。

```json
{"items":[{"id":"1","name":"算法设计与分析（合成演示）","term":"2026-2027-1","role":"STUDENT"}]}
```

role为TEACHER或STUDENT，导航选择应以当前课程为单位。

### GET /courses/{course_id}/assignments

课程教师看课程作业，学生只看自己在名单内且非草稿的作业。返回：

```json
{
  "items": [{
    "id":"2", "title":"演示作业：四类混合题", "submission_status":"OPEN",
    "submission_deadline":"2026-10-28T08:00:00+00:00",
    "review_deadline":"2026-10-30T08:00:00+00:00",
    "items":[{"id":"3","title":"有序数组中的左边界查找","question_type":"ALGORITHM_ANALYSIS","max_score":"100.00","score_weight":"0.250000"}]
  }]
}
```

以上只展示一个作业和一道题作为结构示例。外层items是作业，内层items是作业题目。编程作业review_deadline可空。submission_status不是互评/成绩发布状态，OPEN也不保证还没过deadline。

### GET /assignment-items/{item_id}

教师或参与学生可访问；学生响应字段采用显式白名单，教师调用这里也获得学生可见视图。

| 字段 | 类型 | 含义 |
|---|---|---|
| id、assignment_id | string | 作业题目ID、作业ID |
| problem_code、question_type、title | string | 题号、四类题型、标题 |
| statement_md | string | 完整题干Markdown/LaTeX |
| answer_requirements_md | string/null | 作答要求 |
| input_spec_md、output_spec_md、data_constraints_md、public_examples_md | string/null | 编程说明、范围与公开样例 |
| difficulty_level、version_no | integer | 教师难度1～5、题目内容版本 |
| max_score、score_weight | string | 本次题目满分及作业权重 |
| required_reviewers | integer | 主观题评审人数，编程为0 |
| submission_deadline、review_deadline | datetime string/null | 提交截止必有，评审截止可空 |
| submission_open | boolean | 当前状态与服务端截止综合判断 |
| allowed_languages | string[] | 编程演示为[python3]，主观为空数组 |
| cpu_limit_ms、memory_limit_kib | integer/null | 配置的限制，不是本次实际测量 |
| rubric | object[] | 每维含id、name、description、max_score；编程为空 |

题型值为PROGRAMMING、ALGORITHM_ANALYSIS、PROOF、OPEN_QUESTION。参考答案、标准代码、隐藏用例、上传者身份不会由这个接口返回。

## 4. 正式提交与查询

### POST /assignment-items/{item_id}/submissions

需名单内学生；教师不能代作答。请求：

```json
{"content":"print(1)","language":"python3","client_request_id":"request-001"}
```

| 字段 | 约束 |
|---|---|
| content | 非空且不能全空白；编程最多65536个UTF-8字节，主观最多262144个UTF-8字节；前置字符数上限262144 |
| language | 编程必须是题目allowed_languages之一；主观省略或null |
| client_request_id | 1～64字符，仅A-Z/a-z/0-9/下划线/连字符，区分大小写；由页面生成，不是学生ID |

主观请求示例：`{"content":"证明过程与公式 $T(n)=O(n\\log n)$","client_request_id":"answer-001"}`。

202返回：

```json
{"submission_id":"101","version_no":1,"status":"SUBMITTED","job_status":"PENDING","replayed":false}
```

主观题job_status为AWAITING_REVIEW。同一学生相同键、题目、正文和语言重试，返回同ID、replayed=true，不新增记录；同键不同内容409。截止后仍可重试此前已成功的相同请求；新的请求必须严格早于截止。相同内容但新键是新提交，不自动去重。

### GET /submissions/{submission_id}

仅提交本人或任课教师，另一学生404。返回字段完整示例如下：

```json
{
  "submission_id":"101", "version_no":1, "status":"SUBMITTED",
  "job_status":"SUCCEEDED", "replayed":false,
  "assignment_item_id":"1", "student_id":"11",
  "content":"print(1)", "language":"python3",
  "submitted_at":"2026-10-21T08:00:00+00:00", "withdrawn_at":null,
  "result":{
    "verdict":"MOCK_ACCEPTED", "is_mock":true,
    "algorithm_name":"deterministic_mock", "algorithm_version":"1",
    "cpu_time_ms":null, "memory_kib":null,
    "message":"仅为接口联调模拟结果：未编译、未执行测试，不代表程序正确或正式成绩。"
  }
}
```

等待、主观待评或失败时result可以为空；job_status为PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED，主观无JUDGE任务时派生AWAITING_REVIEW。详情中的replayed默认false，只在提交响应中用它判断本次提交是否重放。详情当前不含题型，题型由assignment_item_id对应的题目取得。

结果中没有score字段，不能根据MOCK_ACCEPTED给100分。真实编译、正式分数、聚合结果是后续接口，不用当前字段冒充。

### POST /submissions/{submission_id}/withdraw

需提交本人，无body要求。截止前且未RUNNING可撤回；PENDING任务取消，源码历史保留。重复撤回返回已有状态，非本人403/404；不允许的状态409。返回与提交回执相同的结构，status为WITHDRAWN。若是主观题，UI优先展示WITHDRAWN，不因派生AWAITING_REVIEW继续参与评审。

## 5. 教师提交列表

### GET /teacher/courses/{course_id}/submissions

仅任课教师；可选查询assignment_item_id、student_id，limit默认20/范围1～100，offset默认0/非负。

```json
{
  "total":1, "limit":20, "offset":0,
  "items":[{
    "submission_id":"101", "student_id":"11", "assignment_item_id":"1",
    "version_no":1, "status":"SUBMITTED", "submitted_at":"2026-10-21T08:00:00+00:00"
  }]
}
```

按提交ID倒序，列表不返回源码，详情按submission_id另取。当前没有class_id过滤和按学生历史的独立学生列表；分别由T/S后续扩展，不应假定传参已生效。

## 6. 前端对接检查

登录 → courses选择课程和角色 → assignments选择题目ID → item详情 → submit保存返回的submission_id → 轮询detail直到终态。主观提交停止判题轮询，显示待互评；失败提供重新查询/联系教师入口，不自动无限重交新版本。

所有示例ID、截止时间和文本仅说明格式，不应硬编码。多门课程用户的role取当前课程；后端仍有最终权限校验，前端隐藏按钮不构成授权。

错误CORS已覆盖开发源5173；如果使用其他前端端口，T与A一起修改配置和验证，不能在页面关闭浏览器安全策略解决跨域。

## 7. 学生作答、历史与评测（2026-10-24 已实现）

本节记录已落地的学生接口，字段以实现和 `../contracts/openapi.json` 为准；设计依据见 [学生与认证接口设计](../student/api.md)。所有接口都在 `/api/v1` 下，ID 为字符串，时间为 UTC ISO8601。

### 7.1 登录、会话与改密

| 方法与路径 | 状态 | 说明 |
|---|---|---|
| `POST /auth/login` | 扩展 | 兼容原字段，追加 `must_change_password`、`server_time`、`expires_at`、`absolute_expires_at` |
| `GET /auth/session` | 新增 | 读取当前身份与期限，不续期 |
| `POST /auth/renew` | 新增 | 由真实操作触发，空闲窗口 2 小时、绝对上限 24 小时，不旋转 token |
| `POST /auth/change-password` | 新增 | `{current_password,new_password}`；同时删除该账号全部旧会话并返回新 token |
| `POST /auth/logout` | 已有 | 删除当前会话 |

- 首次改密前除上述会话、续期、改密、退出外一律 `403 PASSWORD_CHANGE_REQUIRED`。
- 登录限流默认账号＋来源 5 次/分钟、来源 300 次/分钟，失败 10 次/10 分钟进入 `429 LOGIN_COOLDOWN`；计数存 PostgreSQL，多 API 进程共享。
- 登录、改密、重置共用同一用户行锁并重新读取密码哈希，旧密码登录不会在改密提交后插入新会话。

### 7.2 作业与题目读取

| 方法与路径 | 说明 |
|---|---|
| `GET /assignments/{assignment_id}` | 学生安全作业视图：`submission_open`、`server_time`、题目摘要；草稿作业与非名单学生 404 |
| `GET /assignment-items/{item_id}` | 在原有字段上追加 `problem_version_id`、`server_time`、`public_test_cases`（仅 `is_public=true`，`case_no` 从 1 起）；主观题为空数组 |

隐藏输入输出、教师参考与私有配置不进入学生响应。`submission_open` 是服务端当时的判定，前端缓存不能替代。

### 7.3 提交、撤回与重评

`POST /assignment-items/{item_id}/submissions` 维持 `{content,language,client_request_id}` 与 202 回执。新编程任务在 `analysis_jobs.parameters` 固化 `test_suite_id`、`problem_version_id`、`execution_mode`、`runtime_profile`，客户端不能指定模式或运行配置。接收顺序为：限频 → 接收容量锁 → 个人积压（默认 20）／节点积压 → 用户锁 → 名单锁 → 幂等复查 → 截止校验 → 同事务写入提交与任务。

`POST /submissions/{submission_id}/rejudge` 只接受无有效结果的设施 `FAILED`：同键重放返回原回执，冷却 60 秒，学生累计 3 个恢复周期、账号每小时 10 个；换键不能绕过。正常 AC／WA／CE 结果不接受此入口。

### 7.4 详情、历史、进度与任务发现

- `GET /submissions/{submission_id}` 追加 `job`（`status/phase/queue_reason/attempt_no/recovery_cycle_no/can_retry/retry_block_reason/retry_after_at`）与扩展 `result`（`passed_cases/executed_cases/total_cases/execution_mode/runtime_profile/measurement_status/compiler_message/diagnostics_expired`），并补充 `assignment_id`、`course_id` 以便页面跳转。
- `GET /me/submissions` 支持 `course_id/assignment_id/assignment_item_id/language/status/limit/offset`，按 `submitted_at DESC, id DESC`；列表不含正文；越权筛选 404。
- `GET /courses/{course_id}/my-progress` 返回本人逐题 `has_submitted/has_passed/submission_count/active_submission_count/latest_submission_id/best_submission_id/effective_submission_id/has_unresolved_jobs`，`summary` 覆盖完整过滤范围，`evaluation_context` 标明当前执行环境。
- `GET /me/judge-jobs` 的 `filter=DISCOVERY&limit≤100&cursor` 以首次 `scan_high_watermark` 为界做 ID 升序 keyset 扫描，游标绑定账号、课程、过滤与上界并带 HMAC，伪造或过期返回 `422 INVALID_CURSOR`。
- `POST /me/judge-jobs/status` 每次 1～100 个不重复 ID；任一 ID 不可见则整批 404，不暴露哪个 ID 存在。
- `queue_reason` 取值为 `RETRY_BACKOFF`（自动重试退避中）、`SERVICE_PAUSED`（运维暂停领取）、`PERSONAL_LIMIT`（本人已占满 3 个执行名额）、`RESOURCE_WAIT`（等待节点名额），四者按此优先级判定；运维暂停通过 `JUDGE_SERVICE_PAUSED=1` 设置，已接收任务保留排队，恢复后继续领取。

### 7.5 结果语义

`LOCAL` 是本机真实执行：`is_mock=false`、`execution_mode=LOCAL`、`measurement_status=UNAVAILABLE_LOCAL`，`cpu_time_ms` 与 `memory_kib` 为 `null`，不得据此生成 MLE，也不因空资源降级为 Mock。`CE` 的 `executed_cases=0`、`measurement_status=NOT_EXECUTED`。`MOCK` 继续为 `is_mock=true` 且不参与 `has_passed` 与最佳候选。最佳候选比较键为 `(-passed_cases, cpu_time_ms?, memory_kib?, -submitted_at, -version_no, -submission_id)`，空资源后置、同为空时继续比较最近提交。

### 7.6 接收保护与错误

| 状态／code | 含义 |
|---|---|
| `413 REQUEST_TOO_LARGE` | 超过接口专属请求体上限（登录／续期／改密 8 KiB、提交 2 MiB、批量状态 32 KiB），流式或伪长度同样累计 |
| `429 RATE_LIMITED` / `SUBMISSION_BACKLOG_LIMIT` / `JUDGE_RETRY_COOLDOWN` | 限频、个人／节点积压、重评冷却，带 `Retry-After` 与 `retry_after_at` |
| `503 JUDGE_BACKLOG_FULL` | 节点积压达到上限，明确未接收 |
| `409 JUDGE_RETRY_NOT_ALLOWED` / `JUDGE_RETRY_BUDGET_EXHAUSTED` / `JUDGE_CONFIGURATION_UNSUPPORTED` | 状态不允许重评、累计预算耗尽、永久配置故障 |

CORS 已暴露 `X-Request-ID` 与 `Retry-After`。所有 429／503 表示“未接收”，前端保留草稿，不自动延长截止时间。

## 8. 教师与学生联调增量（2026-10-25）

教师账号开通/一次性发放/重置、作业草稿/发布/截止开关与共享采用查询已实现，准确DTO见[教师API第6节](../teacher/api.md)。数据库head为pg0004，沿用pg0002认证与pg0003评测结构，新增测试集总预算。学生题目只追加安全execution_budget字段，含预算及TEACHER/LEGACY_DERIVED来源；学生作答页只读展示，接口不下发隐藏内容。全部旧会话在教师重置时失效，首次改密及续期策略仍由共享认证统一执行。
