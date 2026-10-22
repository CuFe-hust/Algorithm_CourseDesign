# 下一阶段协作接口提案与实施状态

状态：教师题库、版本与名册导入已在本轮实现，精确请求格式以 [teacher_api.md](../teacher_api.md) 和 OpenAPI 为准。以下作业发布、成绩、互评与分析条目仍为提案，未实现接口调用会404。不得把提案当作已上线能力。

保持/api/v1、Bearer、字符串ID、UTC、十进制分数字符串和统一错误格式。T负责教师操作入口，S负责本人作答/评价，A负责分析服务与结果；T的开放/处置/发布接口调用A服务，而不是各写一套算法或改分表。

## 1. T：教师写入接口状态

| 接口 | 请求要点 | 返回要点 / 状态 |
|---|---|---|
| POST /teacher/courses/{course_id}/students/import/preview | multipart CSV文件，列student_no/full_name/class_name | 已实现；content_sha256、签名令牌、行号、问题和数量 |
| POST /teacher/courses/{course_id}/students/import/confirm | 同文件+expected_sha256+preview_token+allow_updates | 已实现；确认时重校验数据库现状 |
| GET/POST /teacher/courses/{course_id}/problems | 课程、题型、题号；详情包含草稿/版本 | 已实现；创建返回完整版本；教师专用DTO |
| POST /teacher/problems/{problem_id}/versions | source_version_id；复制冻结版本后编辑草稿 | 已实现；不覆盖旧冻结版本 |
| POST /teacher/courses/{course_id}/assignments | 标题、截止、选题/分值/权重、目标名单 | 草稿作业ID，尚不可被学生访问 |
| POST /teacher/assignments/{assignment_id}/publish | 明确发布该草稿 | 发布信息、固定名单人数和题目版本 |
| GET /teacher/courses/{course_id}/grades | assignment_id/student_id/class_id与分页 | 已发布成绩、缺交/待评分类、发布版本；不能引用mock判定给分 |

导入确认不得信任预览时的旧数据库状态，重新检查并事务写入。参考答案/隐藏测试只能在教师专用配置接口返回，不复用学生详情DTO。

作业草稿输入示例：

```json
{
  "title":"第一阶段作业",
  "submission_deadline":"2026-11-01T12:00:00+00:00",
  "review_deadline":"2026-11-03T12:00:00+00:00",
  "items":[{"problem_version_id":"31","max_score":"100.00","score_weight":"1.000000","rubric_id":"21","required_reviewers":2}],
  "student_ids":["11","12","13","14","15","16"]
}
```

这只是DTO提案；编程item填写test_suite_id且required_reviewers=0，主观填写rubric_id。用已有数据校验同课程、冻结状态和每题恰好一种配置。

## 2. T→A：互评开放、处置和发布建议

| 教师入口（规划） | A需提供的服务行为 | 关键输出 |
|---|---|---|
| POST /teacher/assignment-items/{item_id}/reviews/preview | 固定候选答案与评审人群，运行匹配预览 | preview_id、输入版本、is_mock、可行性、负载/完整性和未满足约束 |
| POST /teacher/review-previews/{preview_id}/publish | 检查预览未过期、输入未变，原子发布任务 | round_id、任务数、开放时间/操作人 |
| POST /teacher/review-rounds/{round_id}/close | 锁定评价，创建聚合/检测任务或预览 | 计算任务ID与状态 |
| POST /teacher/anomalies/{anomaly_id}/resolution | 验证教师决定并统一执行，必要时重算/补评 | resolution_id、状态、受影响结果版本 |
| POST /teacher/assignments/{assignment_id}/grades/release | 完整性检查，冻结题分/总分/依据，新增发布 | release_id、version_no、发布时间 |

处置请求建议包含action、reason、expected_version与request_id；action候选KEEP、DOWNWEIGHT、INVALIDATE_AND_REVIEW、OVERRIDE_SCORE。具体降权范围和手工分字段在A02前共同确认；相同评价多规则命中不得重复乘权重。失败不先显示“已处理”。

## 3. S：匿名任务与评价建议

| 接口（规划） | 权限与返回 |
|---|---|
| GET /review-tasks | 仅本人任务，支持status分页；无任务返回items空数组 |
| GET /review-tasks/{task_id} | 本人的匿名题干/答案/要求/量表，第一次读取由服务端计时 |
| POST /review-tasks/{task_id}/evaluation | 本人有效任务、未截止；按量表维度评分且评语必填 |
| GET /me/submissions | 只列本人历史，按作业/题目分页；复用当前详情权限 |
| GET /me/grades | 只列本人当前有效已发布成绩与匿名意见，未发布明确待评 |

评审任务学生DTO提案：

```json
{
  "task_id":"401", "round_id":"51", "status":"OPENED",
  "question":{"title":"证明题","statement_md":"题干","answer_requirements_md":"要求"},
  "answer_snapshot_md":"被评答案，不含署名和作者标识",
  "rubric":{"id":"21","items":[{"id":"61","name":"正确性","max_score":"100.00","description":"评分说明"}]},
  "opened_at":"2026-10-21T08:00:00+00:00",
  "deadline":"2026-11-03T12:00:00+00:00",
  "is_mock":true
}
```

学生DTO禁止author_id/学号/真实姓名、原submission_id、文件路径及其他评审者列表。后台匹配结果可以包含真实映射，不能直接返回给S。文字中自行署名需要界面提示与教师处理规则。

评价请求提案：

```json
{"scores":[{"rubric_item_id":"61","score":"85.00"}],"comment":"论证基本完整，建议补充边界。","client_request_id":"review-submit-001","expected_version":0}
```

评分不得缺维度、出现额外维度或越过分值范围，评论非空；revision/expected_version规则由A和S在任务落地前确认。服务端记录开始/提交时间，不能信任客户端自报耗时。

## 4. A：统计和算法接口建议

教师统计建议GET /analysis/courses/{course_id}/overview，学生统计GET /analysis/me/overview。均需权限；响应至少标明time_range、sample_count、missing_count、pending_count、grade_release_version和is_mock。经验难度与教师设定难度分开。

算法核心应独立于FastAPI和SQLAlchemy，使用稳定DTO：

| 算法 | 输入 | 输出 |
|---|---|---|
| allocation | answer_snapshot_id/作者、候选评审者、每份人数、禁止关系、历史、seed | 完整assignment列表或不可行报告、工作量指标、实现版本、is_mock |
| aggregation | 作品、冻结量表、原始评价/有效性/权重、方法参数 | 归一化分、有效样本数、方法与依据、版本、is_mock |
| detection | 评分、时长、历史与关系快照、阈值配置 | 异常类型、对象、证据、样本量、证据不足、版本、is_mock |

第一阶段可用确定性的简单方法和模拟分析指标，但匹配硬约束、评分上下界、权限与发布规则必须真实校验。后续替换算法，输入输出结构和前端读取方式保持稳定。模拟值生成一次落库，不每次读页面重新随机。

## 5. 先补契约的顺序

A01先交评审数据与匿名DTO → T的开放入口和S互评组件并行 → A02交聚合/检测/教师处置 → T复核、S反馈并行 → A03交发布/统计及真实评测。复杂算法研究不阻塞前两步，但不能宣称模拟效果已经通过实验验证。
