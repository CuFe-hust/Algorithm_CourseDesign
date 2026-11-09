/**
 * Synthetic API used only for UI review screenshots.
 *
 * It returns fixed fixtures for a student course and a teacher course so the
 * Vite dev server can render representative pages without a database. It never
 * reads or writes real course data. Run with `node mock-api.mjs 8000`.
 */
import http from "node:http";

const port = Number(process.argv[2] || 8000);
const now = "2026-11-09T10:00:00+08:00";
const deadline = "2026-11-16T23:59:00+08:00";

const session = {
  user: { id: "1", login_name: "demo.student01", full_name: "林晓" },
  must_change_password: false,
  server_time: now,
  expires_at: "2026-11-09T18:00:00+08:00",
  absolute_expires_at: "2026-11-16T18:00:00+08:00",
};

const courses = {
  items: [
    {
      id: "1",
      name: "算法设计与分析（2026 秋 · 合成）",
      term: "2026 秋",
      role: "STUDENT",
    },
    {
      id: "2",
      name: "算法设计与分析（2026 秋 · 合成）",
      term: "2026 秋",
      role: "TEACHER",
    },
  ],
};

const rubric = [
  {
    id: "r1",
    name: "问题建模",
    description: "是否说明了输入输出、约束和关键状态。",
    max_score: "30",
  },
  {
    id: "r2",
    name: "算法正确性",
    description: "关键步骤、边界情况和正确性依据是否完整。",
    max_score: "40",
  },
  {
    id: "r3",
    name: "复杂度与表达",
    description: "时间空间分析是否准确，文字是否清楚。",
    max_score: "30",
  },
];

const question = {
  title: "区间调度：按结束时间贪心",
  statement_md:
    "给定若干区间，选择最多的互不重叠区间。请说明贪心选择、正确性依据与复杂度。",
  answer_requirements_md:
    "需要给出算法步骤、反例检查、时间复杂度与空间复杂度，并说明为什么按结束时间排序。",
};

const assignment = {
  id: "1",
  course_id: "1",
  title: "第一次作业 · 贪心与分治",
  description_md: "本次作业包含编程题与算法分析题。",
  submission_status: "CLOSED",
  submission_deadline: deadline,
  submission_open: false,
  server_time: now,
  items: [
    {
      id: "11",
      title: "区间调度（贪心）",
      question_type: "PROGRAMMING",
      max_score: "100",
      sort_order: 1,
    },
    {
      id: "12",
      title: "区间调度（贪心）",
      question_type: "ALGORITHM_ANALYSIS",
      max_score: "100",
      sort_order: 2,
    },
  ],
};

const assignments = {
  items: [
    {
      id: "1",
      title: assignment.title,
      submission_status: "CLOSED",
      submission_deadline: deadline,
      review_deadline: deadline,
      items: assignment.items,
    },
  ],
};

const submission = {
  submission_id: "1",
  version_no: 2,
  status: "SUBMITTED",
  job_status: "SUCCEEDED",
  replayed: false,
  assignment_item_id: "11",
  assignment_id: "1",
  course_id: "1",
  student_id: "1",
  content:
    "def solve(intervals):\n    intervals.sort(key=lambda x: x[1])\n    end = -1\n    answer = 0\n    for left, right in intervals:\n        if left >= end:\n            answer += 1\n            end = right\n    return answer\n",
  language: "python3",
  submitted_at: "2026-11-08T20:15:00+08:00",
  withdrawn_at: null,
  job: {
    status: "SUCCEEDED",
    phase: "DONE",
    queue_reason: null,
    attempt_no: 1,
    recovery_cycle_no: 0,
    error_code: null,
    message: null,
  },
  result: {
    verdict: "ACCEPTED",
    is_mock: false,
    algorithm_name: "local",
    algorithm_version: "2",
    cpu_time_ms: 42,
    memory_kib: 8192,
    passed_cases: 5,
    executed_cases: 5,
    total_cases: 5,
    execution_mode: "LOCAL",
    runtime_profile: "python3",
    measurement_status: "AVAILABLE",
    message: "全部测试点通过",
    compiler_message: null,
    diagnostics_expired: false,
  },
};

const abilityChapters = [
  ["CH01", "贪心算法", 1.0, 0.819, "OK", 4, 4, 1, 0, 0],
  ["CH02", "分治算法", 0.75, 0.742, "LOW_EVIDENCE", 2, 2, 0, 1, 1],
  ["CH03", "动态规划", null, null, "NO_EVIDENCE", 0, 2, 2, 0, 0],
  ["CH04", "图论", 0.5, 0.533, "OK", 3, 3, 0, 0, 0],
  ["CH05", "搜索与回溯", 0.9, 0.874, "OK", 4, 4, 0, 0, 0],
  ["CH06", "字符串", null, null, "NOT_COVERED", 0, 0, 0, 0, 0],
];
const abilityEstimates = abilityChapters.map(
  ([code, label, value, theta, status, scored, assigned, pending, missing, invalid], index) => ({
    object_key: "student-1",
    dimension: code,
    dimension_label: label,
    dimension_order: index + 1,
    value: value === null ? null : String(value),
    baseline_value: value === null ? null : String(value),
    theta: theta === null ? null : String(Number(theta) - 0.5),
    score_semantics: "REFERENCE_EXPECTED_SCORE",
    status,
    n_items: scored,
    assigned_items: assigned,
    scored_items: scored,
    W_sum: String(scored),
    n_eff: String(scored),
    coverage_items: assigned ? String(scored / assigned) : null,
    coverage_weight: assigned ? String(scored / assigned) : null,
    missing: { pending, not_submitted: missing, invalid },
    observed_min: value === null ? null : "0.5",
    observed_max: value === null ? null : "1",
    diagnostic_flags: status === "LOW_EVIDENCE" ? ["LOW_COVERAGE"] : [],
    by_type: {
      PROGRAMMING: {
        value: value === null ? null : String(value),
        n_items: Math.max(scored - 1, 0),
        W_sum: String(Math.max(scored - 1, 0)),
      },
      SUBJECTIVE: {
        value: value === null ? null : String(value),
        n_items: scored > 1 ? 1 : 0,
        W_sum: scored > 1 ? "1" : "0",
      },
    },
  }),
);

const abilityReport = {
  status: "OK",
  course_id: "1",
  batch_id: "26",
  computed_at: "2026-11-08T21:30:00+08:00",
  is_mock: true,
  source_kind: "SYNTHETIC_FIXTURE",
  results_snapshot_version: "fixture-question-results-v1",
  scoring_policy_version: "synthetic-v1",
  chapter_mapping_version: "question-chapter-map-v1",
  implementation_version: "2",
  scope_label: "合成演示：课程累计章节表现",
  assignment_count: 2,
  method: "DIFFICULTY_FRACTIONAL",
  model_parameters: {
    learner_l2: "0.05",
    item_l2: "0.3",
    difficulty_scale: "0.75",
    max_iterations: 180,
    tolerance: "0.000001",
    calibrate_items: true,
  },
  model_diagnostics: {
    loss: "12.4",
    iterations: 87,
    converged: true,
    score_semantics: "REFERENCE_EXPECTED_SCORE",
    difficulty_source: "TEACHER_PRIOR_WITH_COHORT_CALIBRATION",
  },
  process_diagnostics: {
    available: true,
    items: [
      {
        item_key: "item-11",
        submission_count: 3,
        first_score: "0.5",
        latest_score: "1",
        best_score: "1",
        first_accepted_attempt: 3,
        repeated_failure_pairs: 1,
      },
    ],
  },
  estimates: abilityEstimates,
};

const studentTask = {
  assignment_title: "第一次作业 · 贪心与分治",
  id: "5",
  round_id: "7",
  round_no: 1,
  title: question.title,
  status: "ASSIGNED",
  round_status: "OPEN",
  review_deadline: deadline,
  question,
  answer_content:
    "我先按结束时间排序，然后依次选择与上一个已选区间不重叠的区间。\n\n正确性：设最优解第一个区间为 O1，贪心选择 G1 的结束时间不晚于 O1，因此可以把 O1 替换为 G1 而不减少后续可选区间，归纳可证。\n\n复杂度：排序 O(n log n)，扫描 O(n)，空间 O(1)。",
  rubric,
  rubric_max: "100",
  opened_at: "2026-11-08T20:30:00+08:00",
  can_submit: true,
  evaluation: null,
};

const studentTasks = {
  items: [
    {
      assignment_title: "第一次作业 · 贪心与分治",
      id: "5",
      round_id: "7",
      round_no: 1,
      title: question.title,
      status: "ASSIGNED",
      round_status: "OPEN",
      review_deadline: deadline,
    },
    {
      assignment_title: "第二次作业 · 动态规划",
      id: "6",
      round_id: "8",
      round_no: 1,
      title: "最长公共子序列",
      status: "SUBMITTED",
      round_status: "OPEN",
      review_deadline: deadline,
    },
  ],
  total: 2,
};

const round = {
  id: "7",
  root_round_id: "7",
  assignment_item_id: "12",
  round_no: 1,
  status: "PREVIEW",
  review_deadline: deadline,
  assignment_title: "第一次作业 · 贪心与分治",
  revision: 1,
  root_revision: 1,
  source_hash: "sha256:9f2c…a71b",
  question,
  rubric,
  item_max_score: "100",
  answer_count: 6,
  reviewer_count: 4,
  task_counts: { ASSIGNED: 0, SUBMITTED: 0 },
  allocation: {
    batch_id: "31",
    run_id: "41",
    status: "SUCCEEDED",
    business_status: "OK",
    output: {
      feasible: true,
      unmet_constraints: [],
      load_metrics: {
        "student-101": 3,
        "student-102": 3,
        "student-103": 2,
        "student-104": 2,
      },
    },
  },
  latest_analysis: null,
  analyses: [],
  rounds: [{ id: "7", round_no: 1, status: "PREVIEW" }],
  candidates: { status: "OK", version: 1, rows: [] },
};

const teacherTasks = {
  items: Array.from({ length: 6 }, (_, index) => ({
    task_id: String(100 + index),
    answer_key: `anon-${String(index + 1).padStart(10, "0")}`,
    reviewer_id: `student-${101 + (index % 4)}`,
    status: "ASSIGNED",
    evaluation_id: null,
    total_score: null,
    elapsed_seconds: null,
  })),
  total: 6,
};

const teacherSession = {
  ...session,
  user: { id: "2", login_name: "demo.teacher", full_name: "周老师" },
};

const routes = {
  "/api/v1/courses": courses,
  "/api/v1/assignments/1": assignment,
  "/api/v1/courses/1/assignments": assignments,
  "/api/v1/submissions/1": submission,
  "/api/v1/analysis/submissions/1/complexity": {
    submission_id: "1",
    status: "NONE",
    eligible: true,
    report: null,
    reason: null,
  },
  "/api/v1/courses/1/my-ability/difficulty/demo": abilityReport,
  "/api/v1/courses/1/my-ability/demo": abilityReport,
  "/api/v1/peer-review/tasks/5": studentTask,
  "/api/v1/peer-review/courses/1/my-tasks": studentTasks,
  "/api/v1/peer-review/teacher/rounds/7": round,
  "/api/v1/peer-review/teacher/rounds/7/tasks": teacherTasks,
};

function respond(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(text);
}

http
  .createServer((req, res) => {
    const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);
    const path = url.pathname.replace(/\/$/, "");
    if (path === "/api/v1/auth/session") {
      const authorization = String(req.headers.authorization || "");
      return respond(
        res,
        200,
        authorization.includes("teacher") ? teacherSession : session,
      );
    }
    if (routes[path]) return respond(res, 200, routes[path]);
    if (path.startsWith("/api/v1/")) {
      return respond(res, 404, {
        code: "MOCK_NOT_FOUND",
        message: `No synthetic fixture for ${path}`,
      });
    }
    respond(res, 404, { code: "NOT_FOUND", message: path });
  })
  .listen(port, "127.0.0.1", () => {
    console.log(`mock api listening on http://127.0.0.1:${port}`);
  });
