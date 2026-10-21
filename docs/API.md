# 当前API格式 v1（已实现）

基础地址开发默认 `http://127.0.0.1:8000/api/v1`。本文件只描述main当前可调用接口；新增接口提案见[下一阶段契约](contracts/next-phase.md)。[OpenAPI快照](contracts/openapi.json)可查参数和认证方式，交互文档为 `/docs`。

## 1. 统一格式

- 请求/响应JSON使用UTF-8，字段snake_case。文件上传只在后续教师接口引入。
- ID在JSON中是十进制字符串，前端不转Number；URL和查询参数按其字符串形式拼接。
- 时间为UTC ISO8601，例如 `2026-10-21T08:00:00+00:00`，页面转北京时间；分数/权重用字符串，例如 `100.00`、`0.250000`。
- 成功响应直接返回对象，没有统一data外壳。当前列表返回 `{items:[...]}`，只有教师提交列表增加total/limit/offset。
- 除health、ready、login外均需 `Authorization: Bearer <access_token>`。密码仅在登录body中发送，token不放URL或日志。会话有效2小时，401重新登录。
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
