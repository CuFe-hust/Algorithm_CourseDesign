export interface Page<T> {
  items: T[];
  total: number;
}
export interface Dimension {
  id: string;
  name: string;
  description: string;
  max_score: string;
}
export interface Task {
  assignment_title: string;
  id: string;
  round_id: string;
  round_no: number;
  title: string;
  status: string;
  round_status: string;
  review_deadline: string;
}
export interface TaskDetail extends Task {
  question: {
    title: string;
    statement_md: string;
    answer_requirements_md: string | null;
  };
  answer_content: string;
  rubric: Dimension[];
  rubric_max: string;
  opened_at: string | null;
  can_submit: boolean;
  evaluation: null | {
    id: string;
    scores: { rubric_item_id: string; score: string }[];
    comment: string;
    total_score: string;
    elapsed_seconds: string;
  };
}
export interface Run {
  limitations: string[];
  id: string;
  key: string;
  status: string;
  business_status: string | null;
  implementation: string;
  implementation_version: string;
  reason: unknown;
  output: unknown;
}
export interface Analysis {
  id: string;
  version: number;
  kind: string;
  batch_id: string;
  source_hash: string;
  resolved_at: string | null;
  runs: Run[];
}
export interface Candidate {
  student_id: string;
  answer_key: string | null;
  item_score: string | null;
  normalized_score: string | null;
  reason: string | null;
  source_type: string | null;
  valid_count: number;
}
export interface RoundSummary {
  id: string;
  root_round_id: string;
  assignment_item_id: string;
  round_no: number;
  status: string;
  review_deadline: string;
}
export interface Round extends RoundSummary {
  assignment_title: string;
  revision: number;
  root_revision: number;
  source_hash: string;
  question: TaskDetail["question"];
  rubric: Dimension[];
  item_max_score: string;
  answer_count: number;
  reviewer_count: number;
  task_counts: Record<string, number>;
  allocation: {
    batch_id: string;
    run_id: string;
    status: string;
    business_status: string | null;
    output: null | {
      feasible: boolean;
      unmet_constraints: string[];
      load_metrics: Record<string, number>;
    };
  };
  latest_analysis: Analysis | null;
  analyses: {
    id: string;
    version: number;
    kind: string;
    resolved_at: string | null;
  }[];
  rounds: { id: string; round_no: number; status: string }[];
  candidates: { status: string; version: number; rows: Candidate[] };
}
export interface TeacherTask {
  task_id: string;
  answer_key: string;
  reviewer_id: string;
  status: string;
  evaluation_id: string | null;
  total_score: string | null;
  elapsed_seconds: string | null;
}
export interface Decision {
  action: "KEEP" | "DOWNWEIGHT" | "INVALIDATE" | "OVERRIDE";
  evaluation_id?: string;
  answer_key?: string;
  weight?: string;
  override_score?: string;
  reason: string;
}
export const labels: Record<string, string> = {
  PREVIEW: "待确认预览",
  OPEN: "互评开放",
  CLOSED: "已封存",
  CANCELLED: "已取消",
  READY: "就绪",
  RUNNING: "计算中",
  WAITING_INPUT: "等待输入",
  WAITING_HUMAN: "等待人工确认",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  OK: "证据可用",
  INSUFFICIENT_DATA: "证据不足",
  INFEASIBLE: "分配不可行",
  ASSIGNED: "待评审",
  SUBMITTED: "已提交",
  deviation: "评分偏离",
  reviewer_bias: "评审人偏差",
  review_timing: "评审时长",
  relationship: "关系结构",
  aggregation: "初步聚合",
  reaggregation: "复核后聚合",
  effective_subjective_results: "有效候选结果",
  resolve: "教师复核",
  INITIAL: "初步分析",
  RECOMPUTE: "版本重算",
  PEER_AGGREGATION: "互评聚合",
  TEACHER_OVERRIDE: "教师改分",
  NO_SUBMISSION: "未交作品",
  REVIEW_PENDING: "等待互评处理",
  MINIMUM_SAMPLES_NOT_MET: "有效评价不足",
  INSUFFICIENT_VALID_REVIEWS: "有效评价不足",
};
export const label = (s: string | null | undefined) =>
  s ? labels[s] || s : "—";
export const localDate = (s: string) => {
  const d = new Date(s);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};
