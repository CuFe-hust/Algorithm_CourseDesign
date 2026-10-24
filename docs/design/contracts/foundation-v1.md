# 最小链路契约 v1

## 本轮范围

统一 PostgreSQL 模型与迁移、演示账号、只读题库/作业、正式提交、持久化模拟评测。教师建题与导入页面、完整互评、聚合和正式成绩发布由后续模块实现。

## 通用约定

- 前缀 `/api/v1`；所有 ID 使用十进制字符串。时间 ISO 8601 UTC，带 Z 或 +00:00。
- 登录采用数据库会话：随机 Bearer token，仅保存 token 的 HMAC 摘要，2 小时有效；每次访问重新检查账户状态。前端只使用 Authorization 请求头，不使用自动附带的认证 Cookie。开发 CORS 只允许 localhost/127.0.0.1 的 5173 端口。
- 错误格式 `{code,message,details,request_id}`，响应同时含 X-Request-ID。未登录401；明确禁止动作403；不可见资源404；幂等冲突/截止/作业未开放409；输入无效422；内部故障500且不输出连接信息。
- 学生题目响应不含参考答案、标准实现、隐藏测试、教师参考字段或其他学生身份。
- 编程提交与分析任务同事务保存。主观提交不创建判题任务，不返回伪造分数。
- 模拟评测返回 `MOCK_ACCEPTED`，`is_mock=true`，CPU和内存为空；这是联调结果，不代表程序正确，也不构成正式成绩。

## 接口

| 方法与路径 | 权限 | 行为 |
|---|---|---|
| GET /health | 公开 | 应用存活，不要求数据库 |
| GET /ready | 公开 | 验证数据库与迁移版本；未就绪503 |
| POST /auth/login | 公开 | 输入 login_name、password；输出 access_token、token_type、expires_in、user |
| POST /auth/logout | 已登录 | 作废当前会话 |
| GET /courses | 已登录 | 当前有效课程成员可见的课程及角色 |
| GET /courses/{course_id}/assignments | 课程成员 | 学生只见名单内已发布作业，教师见课程全部作业；含题目ID、题型、截止、满分与权重 |
| GET /assignment-items/{item_id} | 教师或名单内学生 | 指定题目版本的学生可见题干、公开样例、量表、允许语言 |
| POST /assignment-items/{item_id}/submissions | 名单内学生 | 输入 content、language、client_request_id；202返回 submission_id、version_no、status、job_status、replayed |
| GET /submissions/{submission_id} | 本人或任课教师 | 提交内容、作业题目ID、版本、时间、任务状态与允许为空的模拟结果；题型由作业题目查询 |
| GET /teacher/courses/{course_id}/submissions | 任课教师 | 本课程提交列表，支持 assignment_item_id、student_id，分页limit/offset；上限100 |
| POST /submissions/{submission_id}/withdraw | 本人 | 截止前撤回；不修改源码；任务执行器跳过已撤回提交 |

以上路径均省略 `/api/v1`。读取与提交均验证课程有效性、角色和作业应交名单。PENDING/DISABLED账户不能登录。班级、课程角色与身份均不接受客户端冒充。

## 例子

提交：`{"content":"print(1)","language":"python3","client_request_id":"demo-request-001"}`。主观题 language 为空。

编程返回：`{"submission_id":"1","version_no":1,"status":"SUBMITTED","job_status":"PENDING","replayed":false}`。

同一学生的同一client_request_id、题目和内容再次请求返回原记录（replayed=true），不新增版本和任务；同标识更换题目或内容返回409。请求标识严格区分大小写，字段使用utf8mb4_bin排序规则，禁止空白。同一学生的提交通过锁定账号及应交名单行串行分配，连接使用READ COMMITTED避免并发读旧版本。重试先检查既有请求，允许在截止后查询已成功提交的相同请求结果。

## 算法接口

JudgeInput：submission_id、source、language、test_suite_id（ID均字符串），输入由任务消费时从数据库的固定提交和冻结配置读取。

JudgeOutput：verdict（本轮MOCK_ACCEPTED）、is_mock、algorithm_name、algorithm_version、cpu_time_ms、memory_kib、message。资源为非负整数或空，模拟输出必须为空。

命令 `python -m scripts.process_mock_jobs --limit 20` 调用 `process_pending_jobs(session, limit)`；默认一次执行，`--watch`持续轮询。本轮单执行器，进程异常退出后通过 `--recover-running` 将未提交结果的RUNNING任务恢复到PENDING。后续真实评测应升级为租约与超时回收，不使用此基础实现执行学生代码。

## 配置表与运行记录

在13张基础表上补充：test_suites（题目版本、版本号、CPU毫秒、内存KiB、语言列表、判题器、冻结状态），test_cases（测试集、序号、输入输出、权重、公开性），reference_solutions（题目版本、语言、内容、作者），rubrics（题目版本、版本号、名称、冻结状态），rubric_items（维度、满分、说明、顺序），analysis_jobs（提交、类型、状态、参数、实现版本、开始结束、错误），judge_results（唯一任务与提交、判定、模拟标记、资源、说明）。

登录额外使用auth_sessions（用户、唯一token摘要、到期时间）。这不是分析结果表。

已冻结内容通过服务层禁止编辑；首次迁移提供外键、唯一约束、值域检查。题型、跨课程一致性、权重总和和名单规则由公共服务校验。所有调用方复用公共服务，不直接绕过校验写表。

## 范围取舍

- 撤回后复交新建版本，旧提交永久保留；RUNNING任务不允许撤回，PENDING任务随撤回取消。
- 未实现的主观互评不产生模拟评审分；主观状态明确为AWAITING_REVIEW。
- 首版演示代码使用python3，标准实现存在C/C++不意味着本轮已支持多语言执行。
- 无草稿自动保存、无公开注册；示例用户由种子生成，实际导入与账户激活后续由教师模块接入。
