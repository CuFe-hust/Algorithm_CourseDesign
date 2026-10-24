# 学生与认证接口开发设计

日期：2026-10-24。配套 [主开发设计](development.md) 和 [单节点评测设计](judge.md)。

本文中的“新增”“扩展”均是待实现契约。现有接口以 [API.md](../shared/api-v1.md) 和实际路由为准，不修改 OpenAPI 实现快照来假装接口已上线。下述 ID、时间、代码及输出均是结构示例，不是可直接调用的真实数据。

## 1. 公共格式与权限

- 前缀 `/api/v1`；JSON 字段 snake_case；字符串 ID；UTC ISO8601 时间；资源使用 ms 和 KiB。
- 继续使用 Authorization Bearer、数据库会话和现有统一错误 `{code,message,details,request_id}`，保留 `X-Request-ID`。
- 普通列表采用 `{items,total,limit,offset}`，默认 limit=20、上限 100；任务完整发现另用有上界的游标扫描，避免 ACTIVE 集合变化造成 offset 遗漏。现有无分页接口不强行改变结构。
- 业务权限取当前用户及资源所属课程，不接受请求中的 `student_id`、角色或浏览器所选课程作为授权依据。
- 首次改密前只允许会话查询、续期、改密和退出；业务接口返回 403 `PASSWORD_CHANGE_REQUIRED`。
- 本人历史、批量状态、重评只允许课程学生访问本人数据；任课教师沿用教师列表和既有提交详情，不通过 `/me` 冒充学生。
- 他人或不可见资源返回通用 404。网络失败不能伪装成空数据；统计不使用模拟结果当真实通过。

## 2. 接口目录

| 状态 | 方法与路径 | 用途 |
|---|---|---|
| 扩展 | `POST /auth/login` | 兼容原登录，增加首次改密和会话期限 |
| 新增 | `GET /auth/session` | 恢复页面时读取有效身份和期限，不续期 |
| 新增 | `POST /auth/renew` | 实际操作触发的会话续期 |
| 新增 | `POST /auth/change-password` | 首次及主动改密，更换当前凭据并使旧会话失效 |
| 已有 | `POST /auth/logout` | 退出当前会话 |
| 已有 | `GET /courses` | 当前账号可访问课程及各自角色 |
| 已有 | `GET /courses/{course_id}/assignments` | 可见作业和题目摘要 |
| 新增 | `GET /assignments/{assignment_id}` | 直接恢复作业详情，返回学生安全作业视图 |
| 扩展 | `GET /assignment-items/{item_id}` | 增加公开测试、安全题目与提交配置版本 |
| 已有 | `POST /assignment-items/{item_id}/submissions` | 多版本正式提交，202 已接收 |
| 扩展 | `GET /submissions/{submission_id}` | 增加任务反馈、一次提交汇总、执行环境和测量状态 |
| 已有 | `POST /submissions/{submission_id}/withdraw` | 截止前撤回，执行中不可撤回 |
| 新增 | `GET /me/submissions` | 本人提交历史及筛选分页 |
| 新增 | `GET /courses/{course_id}/my-progress` | 作业／逐题提交和通过进度、最近与最佳候选 |
| 新增 | `GET /me/judge-jobs` | 本人任务视图及有上界游标发现 |
| 新增 | `POST /me/judge-jobs/status` | 批量查询本人指定提交的任务状态，只读操作 |
| 新增 | `POST /submissions/{submission_id}/rejudge` | 对服务故障的原提交请求重评 |

账号开通、初始密码发放、密码重置及其管理入口明确归教师端，由教师端负责人实现；学生模块只消费登录、首次改密和续期契约，不自行补教师管理功能。教师端重置服务需遵守首次改密、用户行锁和会话作废契约。

## 3. 登录、改密与续期

### 3.1 POST /auth/login（扩展）

请求沿用现有格式，禁止增加角色字段：

```json
{"login_name":"demo.student01","password":"<本机提供的账号密码>"}
```

成功响应兼容原字段并追加：

```json
{
  "access_token":"<运行时随机凭据>",
  "token_type":"bearer",
  "expires_in":7200,
  "user":{"id":"11","login_name":"demo.student01","full_name":"示例学生"},
  "must_change_password":true,
  "server_time":"2026-10-24T08:00:00Z",
  "expires_at":"2026-10-24T10:00:00Z",
  "absolute_expires_at":"2026-10-25T08:00:00Z"
}
```

待开通／停用账号不能登录；不由登录请求激活账号。前端根据 `must_change_password` 进入改密或课程选择；不根据全局教师身份跳转。密码不进入 URL、草稿或调试日志。

### 3.2 GET /auth/session（新增）

需有效会话，首次改密前也允许。返回与登录相同的 `user`、`must_change_password`、`server_time`、`expires_at` 和 `absolute_expires_at`，不再次返回 token，不延长任何期限。

刷新页面先读取此接口，再获取课程。首次改密账号读取 `/courses` 仍应被业务依赖拦截。

### 3.3 POST /auth/renew（新增）

无业务 body，不接受客户端自报时间覆盖服务端期限。由实际交互事件触发，节流与合并由前端负责。返回：

```json
{
  "server_time":"2026-10-24T08:30:00Z",
  "expires_at":"2026-10-24T10:30:00Z",
  "absolute_expires_at":"2026-10-25T08:00:00Z",
  "must_change_password":false
}
```

续期规则：

1. 按当前 token 查找仍有效的会话，验证账号可用。
2. 以服务端当前时间更新 `last_active_at`，`expires_at=min(now+2h, absolute_expires_at)`。
3. `absolute_expires_at` 从本次登录起固定为 24 小时，续期不改变起点。
4. 通过条件更新和事务处理注销／重置竞争；会话不存在、已到空闲或绝对期限时返回 401，不插入新会话。
5. 不旋转 token，前端仅更新期限，减少轮询与续期之间的凭据竞争；改密时才更换当前凭据。
6. 普通业务读取和状态轮询不自动续期。活跃事件不能证明操作者身份，所有授权仍靠有效会话与资源权限。

前端每次实际操作标记一个新的本地活跃序号，最多每 60 秒上报一次尚未确认的操作；不能用固定计时器反复上报同一次点击。过期返回 401 时保留草稿，重新登录。

### 3.4 POST /auth/change-password（新增）

请求：

```json
{"current_password":"<当前密码>","new_password":"<新密码>"}
```

需要有效会话，首次改密前允许。前端重复输入校验不作为第二份密码字段发送。沿用现有密码哈希基础，密码长度及错误文案需与教师端负责人统一；本方案技术建议为 8～128 字符，不要求额外字符种类，正式编码前将边界写入契约和测试。

- 锁用户，验证当前密码；新旧相同返回 422 `PASSWORD_UNCHANGED`。
- 更新哈希、清除改密标记、更新密码时间，并使该用户旧会话失效。
- 当前浏览器获得新随机 token，响应沿用登录字段；保留原认证起点和绝对上限，改密不偷偷把本次登录延长至另一个 24 小时。
- 原会话删除、新会话及密码更新同事务。旧密码会话不能继续续期或调用业务接口。
- 成功后进入课程选择页。若响应丢失，新密码已生效但浏览器没有新 token，可使用新密码重新登录；不自动重试非幂等改密请求。

### 3.5 登录、改密和重置的串行协议（RV02）

登录不能在锁外验证旧密码后，等改密删会话结束再插入新会话。所有创建密码会话的路径与首次／主动改密、重置共同遵守：

1. 先执行粗粒度登录限流，再在事务中按同一用户行 `SELECT FOR UPDATE`；获取锁后重新读取账号状态和当前密码哈希，不能复用 ORM 身份缓存中的旧值。
2. 登录在该锁内验证当前哈希并创建会话，一次提交。改密／重置同样在该用户锁内更新哈希及删除旧会话。
3. 登录先提交时，随后的改密会删除它；改密先提交时，旧密码登录在锁内重新验证失败。锁不能在创建会话之前释放。
4. 受控开通／重置入口必须调用同一服务协议，不能直接改密码字段而遗漏会话处理。续期只条件更新已有会话，不复活已删除记录。

该协议处理真实的认证竞争，与同账号跨课程混用身份无关，不为后者增加设计。

### 3.6 前端认证代次（RV06）

- 每次派发请求捕获 `auth_generation` 和当前 token；成功登录、改密换凭据及退出推进代次。响应处理前比较代次和凭据快照。
- 只有属于当前凭据的 401 才清当前会话并跳登录。旧 token 请求的迟到 401 直接作为过期请求处理，不能删除新 token。
- 同样保护旧续期的 200、旧账号业务数据和首次改密重定向；不能只防 401 而允许旧响应覆盖新期限或身份。
- 并发登录另用最新登录尝试序号，只有最新尝试可以安装凭据；改密响应也须仍匹配发起时认证上下文。
- `shared/api.ts` 当前的“任意 401 都 clearSession”是待修改代码位置，不是已有防护。续期重试合并只在相同认证代次内共享。

### 3.7 登录和请求体保护（RV03）

登录限流开发默认：账号＋来源组合每分钟 5 次、来源 IP 每分钟 300 次，连续失败 10 次／10 分钟触发短期冷却；值需部署验证，不把短期节流实现为永久停用账号。限流在密码哈希校验前生效，多 API 进程共享计数，来源仅采用可信代理配置，不能信任任意客户端转发头。

请求体上限建议：登录／续期／改密 8 KiB，学生提交 JSON 2 MiB，批量状态 32 KiB。代理和 API 对流式／无 Content-Length 请求同样累计限制，超过返回 413；后续仍校验现有正文 UTF-8 字节上限。按路由设置，不能用学生上限破坏教师已有题目配置或文件导入。

## 4. 作业详情和学生题目视图

### 4.1 GET /assignments/{assignment_id}（新增）

学生须为有效课程成员且在应交名单中；草稿不可见。任课教师也可读取学生安全视图，不返回私有配置。返回：

```json
{
  "id":"21",
  "course_id":"1",
  "title":"第一阶段作业",
  "description_md":"完成下列题目。",
  "submission_status":"OPEN",
  "submission_deadline":"2026-11-01T12:00:00Z",
  "submission_open":true,
  "server_time":"2026-10-24T08:00:00Z",
  "items":[{"id":"31","title":"示例编程题","question_type":"PROGRAMMING","max_score":"100.00","score_weight":"1.000000"}]
}
```

可以由现有列表查询复用服务组装，不硬编码题目 ID。前端不能仅凭缓存的 `submission_status=OPEN` 判断仍能提交。

### 4.2 GET /assignment-items/{item_id}（扩展）

保留当前字段，追加：

```json
{
  "problem_version_id":"41",
  "server_time":"2026-10-24T08:00:00Z",
  "public_test_cases":[
    {"case_no":1,"input_text":"1\n","expected_output":"1\n"}
  ]
}
```

新增片段需与原响应合并，不是完整替代响应。`case_no` 为冻结测试集内从 1 开始的稳定展示序号。只从该作业绑定的测试集筛选 `is_public=true`，无公开测试返回空数组；主观题也返回空数组。

`public_examples_md` 继续独立显示为题面样例。不得调用教师题目详情然后在前端删除隐藏字段；隐藏数据必须不进入学生响应。

## 5. 提交和版本详情

### 5.1 POST /assignment-items/{item_id}/submissions（沿用）

请求和回执保持兼容：

```json
{"content":"print(input())","language":"python3","client_request_id":"request-001"}
```

```json
{"submission_id":"101","version_no":1,"status":"SUBMITTED","job_status":"PENDING","replayed":false}
```

- 主观题 language 省略或 null。字节数、语言、空内容、名单、版本及截止校验沿用现有服务。
- 先查并验证已有幂等记录；新接收事务按 `接收容量锁 -> 用户 -> 名单` 处理，再查一次幂等并校验限额／截止、分配版本，同事务保存提交和任务。重放不消耗新的业务次数，也不因后来队列满或已截止而被当作新提交拒绝。
- 返回 202 只表示已经保存。个人已有 3 份执行时仍可在积压和限频配额内接收；提交限频、个人／节点积压或磁盘水位超限时明确返回 429／503，不假报已接收，保留草稿。
- 新编程任务固定版本／测试集、执行模式和运行配置。开发 LOCAL 真实运行但不测 CPU／内存；后续 Linux 模式单独标记。前端不能传入任意模式、运行镜像或编译命令。
- 语言／配置永久不受支持时提交前返回 409 配置故障，不创建永远排队的任务；可恢复资源不足与永久不支持分开。
- 主观题仍返回派生 `AWAITING_REVIEW`，不创建假任务；显示“已提交，等待后续处理”。

### 5.2 GET /submissions/{submission_id}（扩展）

本人或任课教师权限沿用现有逻辑。保留源码、版本、提交状态和原 `result` 字段，增加结构如下：

```json
{
  "submission_id":"101",
  "version_no":1,
  "status":"SUBMITTED",
  "job_status":"SUCCEEDED",
  "replayed":false,
  "assignment_item_id":"31",
  "student_id":"11",
  "content":"print(input())",
  "language":"python3",
  "submitted_at":"2026-10-24T08:00:00Z",
  "withdrawn_at":null,
  "job":{
    "status":"SUCCEEDED",
    "phase":"FINISHED",
    "queue_reason":null,
    "attempt_no":1,
    "can_retry":false,
    "retry_block_reason":null,
    "error_code":null,
    "message":null
  },
  "result":{
    "verdict":"WRONG_ANSWER",
    "is_mock":false,
    "algorithm_name":"local_judge",
    "algorithm_version":"1",
    "cpu_time_ms":null,
    "memory_kib":null,
    "passed_cases":1,
    "executed_cases":2,
    "total_cases":2,
    "execution_mode":"LOCAL",
    "runtime_profile":"local-dev-v1",
    "measurement_status":"UNAVAILABLE_LOCAL",
    "message":"通过 1 / 2 个测试点",
    "compiler_message":null,
    "diagnostics_expired":false
  }
}
```

本例为本机真实执行，is_mock=false 且资源为空合法，不因此转 FAILED。Linux 测量结果为 execution_mode=LINUX_SANDBOX、measurement_status=MEASURED 并给汇总资源；编译失败用 NOT_EXECUTED。MOCK 仍为 is_mock=true，不混入真实结果。

`runtime_profile` 只给公开配置标签。学生交付不含 case_results 或逐点资源；原始程序输出不作为本轮响应／持久化要求。`result.message` 与 `job.message` 不能复制隐藏输入或输出。

任务和结果规则：

| 情况 | job_status | result / job |
|---|---|---|
| 未执行 | PENDING | result=null；phase=QUEUED 或 RETRY_WAIT |
| 编译／测试／清理旧尝试 | RUNNING | result=null；phase=COMPILING / TESTING / RECOVERING |
| 正常评测结束，包含 CE／WA 等 | SUCCEEDED | result 有真实判定 |
| 服务故障超过自动恢复预算 | FAILED | result=null；can_retry 受冷却、累计预算、熔断及配置是否修复约束 |
| 队列中撤回 | CANCELLED | 源码保留；UI 优先显示 WITHDRAWN |
| 主观答案 | AWAITING_REVIEW | job=null、result=null，不轮询 |

`queue_reason` 为动态提示：RESOURCE_WAIT、PERSONAL_LIMIT、RETRY_BACKOFF、SERVICE_PAUSED，不是队列名次。`can_retry` 由服务端综合计算；受阻时给 retry_block_reason 和可用的 retry_after_at，不能仅因 FAILED 就显示无条件重评。

本轮只返回一次提交汇总，不要求隐藏或公开测试逐点结果。禁止隐藏输入、期望输出、stdout/stderr、差异及可还原内容的自由文本。题目接口仍只外发公开配置。编译诊断经截断和路径处理后返回 compiler_message；保留期结束后置空并标记 diagnostics_expired，不删除正式判定。

### 5.3 POST /submissions/{submission_id}/withdraw（沿用）

截止前且作业 OPEN，执行中不可撤回。撤回 PENDING 同时取消任务；已完成结果保留，但该提交不参与进度和最佳候选。撤回和任务领取竞争时需统一锁顺序，详见评测设计。

## 6. 本人列表、进度与批量状态

### 6.1 GET /me/submissions（新增）

可选筛选：course_id、assignment_id、assignment_item_id、language、status=SUBMITTED|WITHDRAWN，以及 limit/offset。筛选须验证所属关系；不接受 student_id。按 submitted_at DESC,id DESC 排序。语言筛选用于恢复当前语言最近提交；详情正文必须与 language 成对恢复，不能跨语言借正文。

每项返回提交 ID、课程／作业／题目 ID 和标题、题型、版本、时间、语言、状态及紧凑汇总。列表不含正文或编译原文；详情再读取，详情也不要求逐点信息。

总数和列表使用同一过滤条件。越权课程或不一致筛选返回 404，不把无权访问伪装成空列表；合法范围内没有记录返回空 items。

### 6.2 GET /courses/{course_id}/my-progress（新增）

可选 `assignment_id`，只允许当前课程学生。在一个一致读取快照中返回本人可见作业题目的进度；本课程包含题目较多时必须有 limit/offset，响应带总数。

```json
{
  "items":[{
    "assignment_id":"21",
    "assignment_item_id":"31",
    "question_type":"PROGRAMMING",
    "has_submitted":true,
    "has_passed":false,
    "submission_count":2,
    "active_submission_count":2,
    "pending_job_count":1,
    "running_job_count":0,
    "failed_job_count":0,
    "latest_submission_id":"102",
    "best_submission_id":"101",
    "effective_submission_id":"101",
    "has_unresolved_jobs":true
  }],
  "total":1,
  "limit":20,
  "offset":0,
  "evaluation_context":{"execution_mode":"LOCAL","runtime_profile":"local-dev-v1"},
  "summary":{
    "item_count":1,
    "submitted_item_count":1,
    "programming_item_count":1,
    "passed_programming_item_count":0,
    "pending_job_count":1,
    "running_job_count":0,
    "failed_job_count":0
  },
  "as_of":"2026-10-24T08:01:00Z"
}
```

- `submission_count` 包括撤回历史，反映实际主动提交次数；`active_submission_count` 排除撤回。重评不增加任何提交次数。
- `pending_job_count` 只统计 PENDING，`running_job_count` 统计 RUNNING（包含恢复清理阶段），`failed_job_count` 统计服务故障 FAILED；撤回任务不计入上述运行统计。
- 主观题 `has_passed=null`、`best_submission_id=null`，`effective_submission_id` 为最近有效版本。
- 编程题没有真实候选时 best/effective 为 null；不能拿模拟结果补位。最近仍可指向待处理或服务故障版本。
- has_passed 与 best 只在服务器绑定的 evaluation_context 内计算，LOCAL 是真实开发结果但资源未测；不把 LOCAL 与正式 Linux 的资源混排。
- 这是当前候选快照，不是成绩发布或锁定接口。查询不为每次结果创建新的“最终版本”记录。
- `summary` 聚合整个过滤范围而非当前页，并与 items 使用同一读取快照；主观题不计入 programming_item_count 和通过题数。
- 实现需批量查取提交／任务／结果后分组，避免每题重复发查询；分页返回后前端不得把当前页合计冒充全作业总进度。

### 6.3 GET /me/judge-jobs（新增）

可选 course_id，普通视图 filter=ACTIVE|FAILED 使用分页；ACTIVE 对应 PENDING/RUNNING，FAILED 对应服务故障，不包含主观答案。返回本人任务的提交／题目 ID、状态、阶段、排队原因、尝试号、can_retry、安全摘要。

权威发现采用 `filter=DISCOVERY&limit=100&cursor=...`：首次请求固定可见范围内最大 job_id 为 high_watermark，以 ID 升序 keyset 扫描所有状态，返回 items、next_cursor、has_more、scan_high_watermark。游标绑定账号、课程、过滤和上界，不信任客户端任意构造。扫描中任务结束不会从这个集合中消失，避免 ACTIVE+offset 的遗漏；新 ID 在下一轮扫描发现。

前端必须读取到 has_more=false。已知 ID 在终态确认前保留；后续从已扫描上界增量发现新 ID，刷新可重新扫描。还需周期性 keyset 扫描 ACTIVE 来发现旧 ID 经其他页面／维护恢复后重新执行的情况；该扫描允许下轮收敛，不用 offset 猜全集。权限减少时只返回当前可见记录，课程整体失权返回 404，游标过期重新扫描。普通 ACTIVE 的 offset 视图仅用于展示。

### 6.4 POST /me/judge-jobs/status（新增）

请求：

```json
{"submission_ids":["101","102"]}
```

仅查询，不改变活跃时间或任务。最多 100 个不同 ID，前端超过上限时分批，每次最多两个并发批次。逐个验证本人可见性；存在不可见 ID 整体返回通用 404，不返回哪个 ID 存在或属于谁。每项返回提交状态、任务和汇总，不含源码。

批量查询需要覆盖进入终态的任务，不能仅返回仍 ACTIVE 的任务而让前端永远不知道任务已结束。新增任务可从提交回执或本人任务列表发现。

遇整体 404，停止旧集合并刷新课程权限，使用 DISCOVERY 重建当前可见 ID，再分批恢复；不循环重发旧批次，也不通过逐个探测暴露不可见资源。连续变化时退避并提示重新载入。每个批次响应同时受认证代次及课程请求序号保护。

## 7. 服务故障重评

### POST /submissions/{submission_id}/rejudge（新增）

请求：

```json
{"client_request_id":"retry-request-001"}
```

仅本人学生可调用，格式沿用提交请求标识规则。成功 202：

```json
{"submission_id":"101","job_status":"PENDING","replayed":false}
```

事务语义：

1. 验证当前课程身份和名单、原提交未撤回，固定原提交内容及原测试／运行配置。
2. 优先读取持久化重评请求去重记录；同人同键同提交重放返回原回执，改提交重用键返回 409。
3. 原任务必须是设施 FAILED、无有效结果且旧执行已确认清理；永久配置故障先要求配置修复。排队／执行中返回 409 JUDGE_RETRY_NOT_ALLOWED。
4. 不检查当前作业是否还 OPEN，也不要求当前时间早于 DDL；这是处理已接收提交，不接收新内容。
5. 检查任务 60 秒冷却、累计最多 3 个学生恢复周期、账号每小时 10 个新周期及配置熔断；换请求 ID 不能绕过计数。通过后同任务回 PENDING，重置周期内自动预算，累计尝试和手动周期只增不减。
6. 保存请求去重记录和任务变化后一次提交。相同请求重试不重置预算；不同请求竞争仅一个被接收。

不能用此接口重刷正常 AC/WA/CE/TLE 等结果，不接受正文、语言、测试集 ID 或任意运行配置。基础设施自动重试不经过学生接口。

前述数字为开发默认，部署前压测确认。达到累计预算时保留原提交并说明需维护人员处理，不无限重新开周期。幂等重放返回既有回执且不重复消耗业务次数；粗粒度 HTTP 防滥用仍可计数。

## 8. 错误及兼容要求

| 状态／code | 含义及前端行为 |
|---|---|
| 401 `AUTH_REQUIRED` / `AUTH_EXPIRED` | 仅匹配当前认证代次时保存草稿、清会话、重登录；旧请求不影响新 token |
| 403 `PASSWORD_CHANGE_REQUIRED` | 保留会话进入首次改密页 |
| 403 `STUDENT_REQUIRED` | 当前课程角色不能执行学生作答操作 |
| 404 `NOT_FOUND` | 不存在或不可见；不展示他人数据 |
| 409 `SUBMISSION_CLOSED` | 刷新状态／DDL，保留编辑内容，不新增重复提交 |
| 409 `IDEMPOTENCY_CONFLICT` | 请求标识被用于不同逻辑内容，停止自动重试 |
| 409 `CONFIGURATION_CONFLICT` | 题目或运行配置不完整，提示联系教师／管理员 |
| 409 `WITHDRAWAL_CLOSED` | 当前时间或任务状态不可撤回 |
| 409 `JUDGE_RETRY_NOT_ALLOWED` | 当前状态不接受新的重评请求，刷新原任务 |
| 409 `JUDGE_CONFIGURATION_UNSUPPORTED` | 永久配置／环境不支持，明确修复入口，不永久排队 |
| 413 `REQUEST_TOO_LARGE` | 请求体超过该路由上限，解析前拒绝，保留答案 |
| 429 `RATE_LIMITED` / `SUBMISSION_BACKLOG_LIMIT` | 限频或积压上限，带 Retry-After；未接收的新内容保留草稿 |
| 429 `JUDGE_RETRY_COOLDOWN` | 冷却中，返回可重试时间；累计预算耗尽则 409 且 can_retry=false |
| 422 输入错误 | 明确字段及字节数／语言原因，保留答案 |
| 500/503 或网络错误 | 展示 request_id／网络状态；不将接收不明当作未提交 |

429 响应需提供 Retry-After 及可用的 retry_after_at；共享客户端应读取并展示，CORS 暴露该响应头。累计恢复预算耗尽使用 409 JUDGE_RETRY_BUDGET_EXHAUSTED；熔断暂停使用 503 JUDGE_SERVICE_PAUSED，均不接收新的恢复周期。

扩展旧接口只追加字段，保留已有含义。实现完成后同步模型、当前 API 文档、OpenAPI 和示例；在此之前不把本提案混入已实现契约。涉及共享认证时必须同时回归教师端已有登录、选课和错误处理。
