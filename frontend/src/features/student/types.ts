export type QuestionType =
  "PROGRAMMING" | "ALGORITHM_ANALYSIS" | "PROOF" | "OPEN_QUESTION";

export interface CourseSummary {
  id: string;
  name: string;
  term: string;
  role: "TEACHER" | "STUDENT";
}
export interface ItemSummary {
  id: string;
  title: string;
  question_type: QuestionType;
  max_score: string;
  sort_order?: number;
}
export interface AssignmentSummary {
  id: string;
  title: string;
  submission_status: "DRAFT" | "OPEN" | "CLOSED";
  submission_deadline: string;
  review_deadline: string | null;
  items: ItemSummary[];
}
export interface AssignmentDetail {
  id: string;
  course_id: string;
  title: string;
  description_md: string | null;
  submission_status: "DRAFT" | "OPEN" | "CLOSED";
  submission_deadline: string;
  submission_open: boolean;
  server_time: string;
  items: ItemSummary[];
}
export interface PublicCase {
  case_no: number;
  input_text: string;
  expected_output: string;
}
export interface RubricDimension {
  id: string;
  name: string;
  description: string;
  max_score: string;
}
export interface ItemDetail {
  id: string;
  assignment_id: string;
  problem_code: string;
  question_type: QuestionType;
  title: string;
  statement_md: string;
  answer_requirements_md: string | null;
  input_spec_md: string | null;
  output_spec_md: string | null;
  data_constraints_md: string | null;
  public_examples_md: string | null;
  difficulty_level: number;
  version_no: number;
  problem_version_id: string;
  server_time: string;
  max_score: string;
  submission_deadline: string;
  review_deadline: string | null;
  submission_open: boolean;
  allowed_languages: string[];
  cpu_limit_ms: number | null;
  execution_budget?: {
    total_budget_ms: number;
    minimum_budget_ms: number;
    maximum_budget_ms: number;
    budget_source: "TEACHER" | "LEGACY_DERIVED";
  } | null;
  memory_limit_kib: number | null;
  public_test_cases: PublicCase[];
  rubric: RubricDimension[];
}
export interface ResultSummary {
  verdict: string;
  is_mock: boolean;
  algorithm_name: string;
  algorithm_version: string;
  cpu_time_ms: number | null;
  memory_kib: number | null;
  passed_cases: number | null;
  executed_cases: number | null;
  total_cases: number | null;
  execution_mode: string | null;
  runtime_profile: string | null;
  measurement_status: string | null;
  message: string;
  compiler_message: string | null;
  diagnostics_expired: boolean;
}
export interface JobView {
  status: string;
  phase: string;
  queue_reason: string | null;
  attempt_no: number;
  recovery_cycle_no?: number;
  error_code: string | null;
  message: string | null;
  can_retry?: boolean;
  retry_block_reason?: string | null;
  retry_after_at?: string | null;
}
export interface SubmissionDetail {
  submission_id: string;
  version_no: number;
  status: "SUBMITTED" | "WITHDRAWN";
  job_status: string;
  replayed: boolean;
  assignment_item_id: string;
  assignment_id: string;
  course_id: string;
  student_id: string;
  content: string;
  language: string | null;
  submitted_at: string;
  withdrawn_at: string | null;
  job: JobView | null;
  result: ResultSummary | null;
}
export interface Receipt {
  submission_id: string;
  version_no: number;
  status: string;
  job_status: string;
  replayed: boolean;
}
export interface ProgressEntry {
  assignment_id: string;
  assignment_title: string;
  assignment_item_id: string;
  title: string;
  question_type: QuestionType;
  has_submitted: boolean;
  has_passed: boolean | null;
  submission_count: number;
  active_submission_count: number;
  pending_job_count: number;
  running_job_count: number;
  failed_job_count: number;
  latest_submission_id: string | null;
  best_submission_id: string | null;
  effective_submission_id: string | null;
  has_unresolved_jobs: boolean;
}
export interface ProgressResponse {
  items: ProgressEntry[];
  total: number;
  limit: number;
  offset: number;
  evaluation_context: { execution_mode: string; runtime_profile: string };
  summary: {
    item_count: number;
    submitted_item_count: number;
    programming_item_count: number;
    passed_programming_item_count: number;
    pending_job_count: number;
    running_job_count: number;
    failed_job_count: number;
  };
  as_of: string;
}
export interface HistoryEntry {
  submission_id: string;
  course_id: string;
  assignment_id: string;
  assignment_title: string;
  assignment_item_id: string;
  title: string;
  question_type: QuestionType;
  version_no: number;
  submitted_at: string;
  language: string | null;
  status: string;
  job_status: string;
  summary: ResultSummary | null;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface BatchStatusEntry {
  submission_id: string;
  status: string;
  job: JobView | null;
  result: ResultSummary | null;
}

/* ---------------------------------------------------------- complexity report */

export type ComplexityClass =
  | "O(1)"
  | "O(log n)"
  | "O(n)"
  | "O(n log n)"
  | "O(n^2)"
  | "O(n^2 log n)"
  | "O(n^3)"
  | "O(2^n)"
  | "UNKNOWN";

export type Confidence = "LOW" | "MEDIUM" | "HIGH";

export interface StaticEvidence {
  line: number;
  reason: string;
  kind: string;
}

export interface StaticAnalysis {
  time_class: ComplexityClass;
  space_class: ComplexityClass;
  confidence: Confidence;
  evidence: StaticEvidence[];
  loop_depth: number;
  max_loop_lines: number[];
  recursive: boolean;
  recursion_kind: string | null;
  logarithmic_loops: number;
  sorts: number;
  dynamic_allocations: number;
  notes: string[];
  profile_family?: string | null;
}

export interface GrowthPoint {
  n: number;
  wall_ms: number;
  reference_ms?: number | null;
  io_ratio?: number | null;
  peak_rss_kib?: number | null;
  verdict: string;
  detail?: string | null;
  repeats?: number;
}

export interface GrowthCurvePoint {
  n: number;
  time_ms: number;
}

export interface GrowthFitPayload {
  fitted_class: ComplexityClass;
  r2: number;
  exponent: number;
  coefficient: number;
  offset_ms: number;
  floor_ms: number;
  confidence: Confidence;
  notes: string[];
  used_points: GrowthPoint[];
  discarded: GrowthPoint[];
}

export interface DynamicAnalysis {
  measured_class: ComplexityClass;
  io_class: ComplexityClass;
  informative: boolean;
  r2: number;
  exponent: number | null;
  confidence: Confidence;
  floor_ms: number;
  fit: GrowthFitPayload | null;
  reference_fit: GrowthFitPayload | null;
  accounting: {
    n: number;
    wall_ms: number;
    reference_ms: number | null;
    io_ratio: number | null;
    peak_rss_kib: number | null;
    verdict: string;
  }[];
  stop_reason?: string;
  rungs?: GrowthPoint[];
  curve?: GrowthCurvePoint[];
}

export interface ComplexitySummary {
  time: {
    class: ComplexityClass;
    confidence: Confidence;
    source: "DYNAMIC" | "STATIC";
    static_class: ComplexityClass;
    measured_class: ComplexityClass;
    agreement: boolean | null;
    r2?: number;
    exponent?: number;
    offset_ms?: number;
    coefficient?: number;
  };
  space: {
    class: ComplexityClass;
    confidence: Confidence;
    source: string;
    static_class: ComplexityClass;
  };
  limitations: string[];
}

export interface ComplexityReport {
  status:
    | "SUCCEEDED"
    | "STATIC_ONLY"
    | "INELIGIBLE"
    | "FAILED"
    | "PENDING"
    | "RUNNING";
  language: string | null;
  implementation_name: string;
  implementation_version: string;
  time: ComplexitySummary["time"];
  space: ComplexitySummary["space"];
  static: StaticAnalysis;
  dynamic: DynamicAnalysis;
  limitations: string[];
  error: string | null;
  requested_at: string | null;
  finished_at: string | null;
}

export interface ComplexityResponse {
  submission_id: string;
  status: ComplexityReport["status"] | "NONE";
  eligible: boolean | null;
  report: ComplexityReport | null;
  reason: string | null;
}
