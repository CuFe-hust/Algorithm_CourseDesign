# 教师端 API 契约（已实现）

基础路径 `/api/v1/teacher`；全部要求 Bearer 和当前课程教师权限。继续遵循 [公共格式](API.md)：ID 为字符串、UTC ISO8601 时间、分值/权重为十进制字符串，统一错误含 `request_id`。完整参数见 [OpenAPI](contracts/openapi.json) 或运行时 `/docs`。

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
