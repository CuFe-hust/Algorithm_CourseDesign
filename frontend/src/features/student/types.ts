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
  score_weight: string;
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
  score_weight: string;
  submission_deadline: string;
  review_deadline: string | null;
  submission_open: boolean;
  allowed_languages: string[];
  cpu_limit_ms: number | null;
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
