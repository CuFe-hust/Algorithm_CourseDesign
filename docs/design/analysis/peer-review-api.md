# 主观互评与复核 API / 下游交接

根路径 `/api/v1/peer-review`。Bearer登录及首次密码更改规则沿用现有底座；任课教师和本人任务权限由服务端检查。全部响应 `Cache-Control: no-store`。分页默认20，最大100，offset≥0。64位ID以字符串传输，分数用十进制字符串，时间带时区；完整字段见 [OpenAPI](../contracts/openapi.json)。

## 教师入口

| 方法 | 相对路径 | 作用 |
|---|---|---|
| GET | `/teacher/courses/{course_id}/rounds` | 本课轮次分页 |
| GET | `/teacher/assignment-items/{item_id}/options` | 主观题当前截止、状态、人数、满分 |
| POST | `/teacher/assignment-items/{item_id}/previews` | 固定源输入，建立分配批次；返回201，不自动开放 |
| GET | `/teacher/rounds/{round_id}` | 固定量表、人数、分配状态、最新分析、轮次/版本索引、最近命令审计、当前候选 |
| POST | `/teacher/rounds/{round_id}/publish` | 校验revision及source_hash，完整任务落库并开放 |
| POST | `/teacher/rounds/{round_id}/cancel` | 仅取消未发布预览，已发布任务不可改写 |
| POST | `/teacher/rounds/{round_id}/deadline` | 仅为开放轮次延长截止，须理由 |
| POST | `/teacher/rounds/{round_id}/close` | 原始评价封存，创建 INITIAL 分析版本 |
| POST | `/teacher/rounds/{round_id}/analyses` | 显式创建新的 INITIAL，不能跳过未复核版本 |
| GET | `/teacher/rounds/{round_id}/tasks` | 分页任务、作品代号、评审ID、原分、服务器时长、评价ID |
| GET | `/teacher/tasks/{task_id}` | 原作品和评价详情；不会启动学生计时 |
| GET | `/teacher/analyses/{analysis_id}` | 指定历史版本、算法/版本、输出/限制、教师决策与理由 |
| POST | `/teacher/analyses/{analysis_id}/resolve` | 原子保存处置及理由；生成 RECOMPUTE 或补评预览 |
| GET | `/teacher/rounds/{round_id}/results` | 当前逐题候选交接；子轮ID也映射主轮 |

预览参数：request_id、review_deadline、reason、policy、forbidden_pairs。policy包含 aggregation_method、minimum_samples、deviation_threshold、deviation_minimum_peers、bias_threshold、history_minimum_samples、short_seconds、timing_relative_fraction、timing_minimum_samples、seed、max_tasks_per_reviewer。每份评审人数来自冻结 AssignmentItem；最低样本不能超过此人数。

发布参数：request_id、expected_revision、expected_source_hash。其他配置命令包含 request_id、expected_revision、reason；延期另传 review_deadline。提前封存且有缺评时须 `accept_incomplete=true`。同ID同内容重试返回replayed，同ID改内容409；无需客户端提供映射或原始评分总分。

复核示例（示意ID；生产调用必须用刚读取的实际值）：

```json
{
  "request_id": "review-resolve-uuid",
  "expected_revision": 2,
  "expected_source_hash": "<当前分析的64位摘要>",
  "reason": "已核对原作品、量表与评价依据，证据不足部分不自动处罚",
  "acknowledged_statuses": {
    "deviation": "OK",
    "reviewer_bias": "INSUFFICIENT_DATA",
    "review_timing": "OK",
    "relationship": "OK"
  },
  "decisions": [
    {"action": "DOWNWEIGHT", "evaluation_id": "101", "weight": "0.5", "reason": "仅部分维度有依据"},
    {"action": "OVERRIDE", "answer_key": "a_作品匿名键", "override_score": "17.50", "reason": "教师按本题20分量表独立复核"}
  ],
  "request_supplement": false
}
```

`expected_revision`为主轮root_revision，source_hash为待复核分析版本摘要；四个确认状态必须与当前检测实际状态一致。每个目标一次请求只允许一个处置；评价和作品目标必须二选一。评价仅允许KEEP/DOWNWEIGHT/INVALIDATE；作品仅允许KEEP/OVERRIDE。补评将 `request_supplement=true` 并传未来 supplement_deadline，不直接开放新任务。

计算失败沿用 `POST /api/v1/analysis/batches/{batch_id}/runs/{run_id}/retry`，同样须本课教师身份，最多3次尝试。`REAL_INPUT`不接受旧 DEMO事件入口。

## 学生入口

| 方法 | 相对路径 | 作用 |
|---|---|---|
| GET | `/courses/{course_id}/my-tasks` | 本课本人任务分页 |
| GET | `/tasks/{task_id}` | 本人匿名作品/量表与评价；首次有效打开记录服务器时间 |
| POST | `/tasks/{task_id}/evaluation` | 全维度评分和评语；同请求ID可安全重试 |

```json
{
  "client_request_id": "evaluation-uuid",
  "scores": [
    {"rubric_item_id": "21", "score": "8.25"},
    {"rubric_item_id": "22", "score": "7.00"}
  ],
  "comment": "关键不变量正确，建议补充终止性与边界条件。"
}
```

不接受 reviewer_id、作者、原总分或 elapsed_seconds。维度集合必须与冻结量表完全一致，每分项0到该维满分、最多两位小数，评语去空格后非空。无法跳过首次打开，不能评自己、他人任务或已截止任务；已接受请求在封存后仍可幂等重放。

## 给第⑤条链路的稳定边界

HTTP：上述 results。内部同事务读取可调用 `app.peer_review.analyses.handoff(db, root)`，调用方先完成课程权限与主轮定位；不要直接修改本模块表。

返回 `schema_version=subjective-candidates-v1`、is_mock、status、root_round_id、analysis_id、version、source_hash、artifact_id、output_hash、policy、rows。每行包含 student_id、assignment_item_id、submission_id、answer_key、normalized_score、item_score、reason、source_type、valid_count。

- 仅最新版本为已完成 RECOMPUTE、且无活动补评时 status=READY。READY表示当前候选产物可读，并不保证每个学生都有分。
- 最新 INITIAL、重算未完成或补评未完成时 WAITING_INPUT；不把旧版本冒充当前结果。
- 未交作品：分数null、submission_id=null、reason=NO_SUBMISSION。
- 有作品但处理未完成：分数null、reason=REVIEW_PENDING。
- 重算后有效样本不足：分数null，保留聚合的明确不足原因及有效数。
- 真实0分保留为字符串0；缺失不能转0。
- `source_type=TEACHER_OVERRIDE`表示教师按本题满分改分，否则为PEER_AGGREGATION；算法与方法版本可从 analysis_id 对应运行记录读取。
- 第⑤条负责人需固定本接口的 artifact_id/output_hash、版本和逐题来源，执行其完整性及发布政策；本模块不产生作业总分或正式成绩发布快照。

## 常见冲突

409：REVIEW_SOURCE_CHANGED、REVIEW_VERSION_CONFLICT、ALLOCATION_INFEASIBLE、DETECTION_NOT_READY、DETECTION_ACK_REQUIRED、EVALUATION_IMMUTABLE、REVIEW_CLOSED、IDEMPOTENCY_CONFLICT等。422：量表不完整、越界分数、非法目标、无时区、超规模。未知数据库错误不会把SQL或私密内容返回浏览器；现有请求编号用于定位。
