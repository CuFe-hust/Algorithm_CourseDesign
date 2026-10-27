# 教师端 API 契约（已实现）

基础路径 `/api/v1/teacher`；全部要求 Bearer 和当前课程教师权限。继续遵循 [公共格式](../shared/api-v1.md)：ID 为字符串、UTC ISO8601 时间、分值/权重为十进制字符串，统一错误含 `request_id`。完整参数见 [OpenAPI](../contracts/openapi.json) 或运行时 `/docs`。

## 1. 接口目录

| 方法与路径 | 说明 |
|---|---|
| `GET /courses/{course_id}/overview` | 在用题目、按题型计数、草稿、学生及班级 |
| `GET /courses/{course_id}/knowledge-points` | 启用的课程知识点 |
| `POST /courses/{course_id}/knowledge-points` | `{name}`；同名启用记录复用，201 |
| `GET /courses/{course_id}/problems` | q、question_type、status=ACTIVE/ARCHIVED、limit、offset |
| `POST /courses/{course_id}/problems` | 创建题目及第一个 DRAFT，201，返回完整版本 |
| `GET /problems/{problem_id}` | 题目信息、版本列表和最新完整版本 |
| `GET /problem-versions/{version_id}` | 教师专用版本详情，含答案和隐藏用例 |
| `PUT /problem-versions/{version_id}` | 完整替换草稿内容与配置，需 expected_updated_at |
| `POST /problem-versions/{version_id}/freeze` | 完整性校验并冻结，需 expected_updated_at |
| `POST /problems/{problem_id}/versions` | `{source_version_id}`；复制冻结版本为下一草稿，201 |
| `POST /problems/{problem_id}/archive` | 归档，不删除历史版本 |
| `POST /problems/{problem_id}/restore` | 恢复为在用题目 |
| `GET /courses/{course_id}/students` | q（姓名/学号）、class_id、limit、offset |
| `GET /courses/{course_id}/classes` | 当前有效学生关联班级 |
| `GET /courses/{course_id}/students/import/template` | UTF-8 BOM CSV 附件 |
| `POST /courses/{course_id}/students/import/preview` | multipart `file`，只读预览 |
| `POST /courses/{course_id}/students/import/confirm` | multipart file、expected_sha256、preview_token、allow_updates |
| `GET /courses/{course_id}/submissions` | 原有提交列表，行为保持兼容 |

题目和学生列表返回 `{items,total,limit,offset}`，默认 limit=20，上限100。列表筛选对原始 `%`、`_` 作为文字搜索，不当作通配符。

## 2. 新建主观题

以下 ID 均为结构示例，使用 `/courses` 和知识点列表取得实际值：

```json
{
  "code": "ANALYSIS-021",
  "question_type": "ALGORITHM_ANALYSIS",
  "version": {
    "title": "递推式与主定理",
    "statement_md": "设 $T(n)=2T(n/2)+n$，且 $T(1)=1$，分析其渐近复杂度。",
    "answer_requirements_md": "写出所用条件与推导过程。",
    "difficulty_level": 3,
    "source_reference": "原创教学示例",
    "knowledge_point_ids": ["31"],
    "reference_solutions": [
      {"language": null, "content": "a=2，b=2，f(n)=n，与 n^(log_b a) 同阶，故 T(n)=Θ(n log n)。"}
    ],
    "rubric": {
      "name": "评分量表",
      "items": [
        {"name": "条件与结论", "description": "正确识别主定理参数与适用条件，给出紧确界。", "max_score": "100.00"}
      ]
    }
  }
}
```

题型取 `PROGRAMMING / ALGORITHM_ANALYSIS / PROOF / OPEN_QUESTION`。题型与题号创建后固定。编程题使用 `test_suite`，主观题使用 `rubric`，不得同时配置。

编程配置字段示例：

```json
{
  "cpu_limit_ms": 1000,
  "memory_limit_kib": 262144,
  "allowed_languages": ["python3", "cpp"],
  "checker": "TEXT_TRIM_TRAILING",
  "cases": [
    {"input_text": "1\n", "expected_output": "1\n", "weight": "1.000000", "is_public": false}
  ]
}
```

编程题的版本内容还需维护 `input_spec_md`、`output_spec_md`、`data_constraints_md`、`public_examples_md`。语言候选为 python3/cpp/c/java；资源设置只是配置，当前平台仍没有真实执行沙箱。

修改版本：

```json
{
  "expected_updated_at": "2026-10-22T08:00:00.123456+00:00",
  "version": {
    "title": "递推式与主定理（修订）",
    "statement_md": "设 $T(n)=2T(n/2)+n$ 且 $T(1)=1$，给出紧确渐近界。",
    "difficulty_level": 3,
    "knowledge_point_ids": ["31"],
    "reference_solutions": [{"language": null, "content": "由主定理得 T(n)=Θ(n log n)。"}],
    "rubric": {
      "name": "评分量表",
      "items": [{"name": "推导", "description": "参数、条件和结论正确。", "max_score": "100.00"}]
    }
  }
}
```

PUT 提交完整的 version 对象，不是部分 PATCH；省略的可选内容会恢复默认值，已有配置不可省略或设 null。例中的知识点 ID 与时间戳替换为实际值。冻结请求仅包含 `expected_updated_at`，必须使用最近一次成功保存响应中的原始时间戳，不做本地时间转换后回传。

## 3. 学生导入

```csv
student_no,full_name,class_name,class_code
000001,合成学生甲,合成一班,CLASS-SAMPLE-1
000002,合成学生乙,合成一班,CLASS-SAMPLE-1
```

前三列必填，class_code 可省略；禁止多余/重复列。示例不是实际名单。学号为1～32位字母、数字、点、下划线、短横线，首位字母或数字。姓名/班名最多100字符。最大2 MiB、2,000行。

预览返回 `valid`、`content_sha256`、`preview_token`、`expires_in=900`、`requires_update_confirmation`、`rows` 和 `summary`。行对象包含原始字段、物理 CSV 行号 `row_number`、`resolved_class_code`、`action`、`errors` 与变更字段名 `changes`。有任何行错误时 `valid=false` 且 token=null，不能确认。

`summary` 字段：`created_students` 新身份数、`enrolled_students` 新增或恢复课程成员数、`updated_profiles` 已有资料变化数、`unchanged_students` 完全一致数、`created_classes` 新班级数。计数允许重叠，例如一个新学生同时计入新身份和课程关联。

确认时重新上传原文件，并传相同摘要与预览令牌；`allow_updates` 默认 false，存在允许的资料更新时必须 true。成功返回 `status=imported`、`summary`、`rows`（行数）、`replayed`、`content_sha256`。所有目标已一致时安全返回 replayed=true。

## 4. 主要错误码

| HTTP / code | 客户端处理 |
|---|---|
| 401 / UNAUTHORIZED 等共享认证错误 | 清理会话并重新登录 |
| 403 / TEACHER_REQUIRED | 当前身份不能操作教师接口 |
| 404 / NOT_FOUND | 资源不存在或不属于可访问课程 |
| 409 / VERSION_CONFLICT | 保留本地草稿供核对，重新读取最新版本再提交 |
| 409 / VERSION_FROZEN | 查看原版本或复制新草稿 |
| 409 / DRAFT_EXISTS | details.version_id 指向已有草稿 |
| 409 / PROBLEM_CODE_EXISTS、PROBLEM_ARCHIVED | 更换题号或先恢复题目 |
| 422 / WRONG_CONFIGURATION、INVALID_KNOWLEDGE_POINT、CONFIGURATION_REQUIRED | 修正题型配置或知识点；已有配置不能置 null |
| 422 / FREEZE_VALIDATION_FAILED | 展示 details.requirements，完善后重新保存/冻结 |
| 422 / INVALID_CSV_*、EMPTY_ROSTER、TOO_MANY_ROWS | 修正文件；逐行错误也可能以200 valid=false返回 |
| 409 / FILE_CHANGED、PREVIEW_EXPIRED、PREVIEW_STALE、ROSTER_CONFLICT | 重新预览，不自动跳过错误行 |
| 409 / UPDATE_CONFIRMATION_REQUIRED | 核对变更后明确确认 |
| 409 / WRITE_CONFLICT | 事务已回滚；刷新或重新预览 |

未列出的字段校验错误沿用共享 422 格式。客户端不能以 HTTP 200 预览响应作为实际写入成功的依据。

## 6. 学生作答联调接口（2026-10-25 已实现）

以下接口全部要求有效、已完成首次改密的当前课程教师。未加入课程404，学生身份403。成功写入原子提交；ID保持字符串，时间带时区。

| 方法与路径（相对 `/api/v1/teacher`） | 输入与结果 |
|---|---|
| `POST /courses/{course_id}/students/credentials` | action为ACTIVATE/RESET；students为1～50个 `{student_id,expected_updated_at}`。仅本次响应返回credentials及issued_at，no-store |
| `GET /courses/{course_id}/judge-capabilities` | 当前execution_mode、driver_available、实际supported_languages、maximum_budget_ms与预算公式参数 |
| `GET /courses/{course_id}/assignment-choices` | 冻结且在用题目的各版本，q/limit/offset；返回版本和最新冻结配置ID，不返回隐藏测试正文 |
| `GET /courses/{course_id}/assignments` | 作业列表，limit/offset；标题、状态、截止、更新时间、题数和人数 |
| `POST /courses/{course_id}/assignments` | 下述草稿DTO，201返回教师完整详情 |
| `GET /assignments/{assignment_id}` | 课程、标题、状态、截止、发布信息、更新时间、固定items与participants班级快照 |
| `PUT /assignments/{assignment_id}` | `{expected_updated_at,assignment:草稿DTO}`；仅DRAFT可完整替换 |
| `POST /assignments/{assignment_id}/publish` | `{expected_updated_at,submission_status:"CLOSED"或"OPEN"}`；默认CLOSED，仅发布一次 |
| `POST /assignments/{assignment_id}/schedule` | `{expected_updated_at,submission_deadline,review_deadline,submission_status}`；已发布作业的截止与开关 |
| `GET /courses/{course_id}/students/{student_id}/progress` | 可选assignment_id、limit/offset；复用学生progress结构，追加student姓名/学号，仅当前授权课程 |

### 6.1 凭据管理

ACTIVATE仅接受PENDING，RESET仅接受ACTIVE；DISABLED不会自动启用。目标须为本课程有效STUDENT成员且有学生资料，不能有有效教师身份。重复目标、未知字段、无时区时间拒绝。更新时间过期409 `ACCOUNT_CONFLICT`，状态不符409 `ACCOUNT_STATE_CONFLICT`。任何一人失败整批回滚。

每人生成独立随机初始密码，保存哈希，设置 `must_change_password=true`、`password_updated_at` 和ACTIVE，删除全部旧会话。响应只在 `credentials[].initial_password` 返回一次，普通名单永不包含密码；名单追加 `updated_at` 和 `must_change_password`。教师逐人发放或下载清单，不调用外部消息服务。响应丢失后刷新名单并显式重置，不能查询旧明文。

### 6.2 作业草稿DTO

```json
{
  "title": "算法分析第一阶段作业",
  "description_md": "请给出推导过程。",
  "submission_deadline": "2026-11-01T12:00:00Z",
  "review_deadline": "2026-11-03T12:00:00Z",
  "items": [{
    "problem_version_id": "31",
    "test_suite_id": null,
    "rubric_id": "21",
    "max_score": "100.00",
    "required_reviewers": 3
  }],
  "student_ids": ["11", "12"]
}
```

items数组顺序就是题目顺序，最多100题；student_ids最多2000且唯一。编程题必须test_suite_id、rubric_id=null、required_reviewers=0；主观题反之且评审人数1～10。分值为正且最多两位小数，权重(0,1]且最多六位小数。草稿可无题或无名单；引用的题目仍必须冻结、同课程且配置属于该版本。发布要求至少一题/一人、未来截止及完整题干/参考/知识点/配置。

发布事务重取学生当前班级，保存班级快照并固定发布者和时间；PENDING学生允许进入名单，但需教师开通才可登录。之后导入学生不会自动改变旧名单。发布后PUT返回409 `ASSIGNMENT_PUBLISHED`，只能通过schedule调整截止和开关；不改历史答案或评测。OPEN需未来截止并通过当前节点检查，CLOSED保持可读；评审截止若存在必须晚于提交截止。作业更新时间过期409 `ASSIGNMENT_CONFLICT`。

### 6.3 测试集总预算

教师SuiteInput和教师版本详情新增 `total_budget_ms`（整数ms，可空输入）。新保存的空输入会生成当前配置的预算值，写入独立配置快照；旧冻结测试集保持NULL，读取/执行时推导并标记来源。

`minimum = 30000 + N * (max(1000, 3 * cpu_limit_ms) + 250) + 5000`；编译、逐点墙钟、启动和清理预留都纳入。节点上限默认300000 ms，通过 `JUDGE_MAX_TOTAL_BUDGET_MS` 调整，绝对不超过3600000。冻结、发布与重开校验最低值和节点上限；OPEN还检查驱动与实际工具链。非法配置422，requirements列出原因，不生成永远等待的任务。

学生题目详情只追加安全字段 `execution_budget:{total_budget_ms,minimum_budget_ms,maximum_budget_ms,budget_source}`，来源为TEACHER或LEGACY_DERIVED，不返回参考代码或隐藏输入输出。预算由调度读取固定suite并传入LOCAL执行，编译与用例共用全题截止；LOCAL仍不测CPU/内存，不伪造值。

### 6.4 查询采用候选

教师progress调用共享 `student.records.course_progress()`，不以最新编程提交替代最佳；Mock及其他环境结果不混比。通过数、空资源、最近版本和未解决任务口径与学生端一致。仅有候选不代表正式成绩，互评和成绩发布仍未交付。查看源码及结果复用既有 `GET /api/v1/submissions/{id}` 教师权限；历史复用教师submissions筛选。
