import type { QuestionType } from "./types";
export interface AssignmentChoice {
  problem_version_id: string;
  code: string;
  title: string;
  version_no: number;
  question_type: QuestionType;
  test_suite_id: string | null;
  rubric_id: string | null;
}
export interface AssignmentItem extends AssignmentChoice {
  id?: string;
  max_score: string;
  score_weight: string;
  required_reviewers: number;
}
export interface AssignmentDetail {
  id: string;
  course_id: string;
  title: string;
  description_md: string | null;
  submission_status: "DRAFT" | "OPEN" | "CLOSED";
  submission_deadline: string;
  review_deadline: string | null;
  updated_at: string;
  published_at: string | null;
  items: AssignmentItem[];
  student_ids: string[];
  participants: {
    student_id: string;
    student_no: string | null;
    full_name: string;
    status: string;
    class_name_at_publish: string;
  }[];
}
export interface RosterStudent {
  id: string;
  student_no: string | null;
  login_name: string;
  full_name: string;
  status: string;
  class_name: string | null;
  updated_at: string;
  must_change_password: boolean;
}
export function localDate(value: string) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
export function utcDate(value: string) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime()))
    throw new Error("请填写有效的截止时间。");
  return date.toISOString();
}
export function assignmentPayload(
  title: string,
  description: string,
  deadline: string,
  review: string,
  items: AssignmentItem[],
  studentIds: string[],
) {
  return {
    title: title.trim(),
    description_md: description,
    submission_deadline: utcDate(deadline),
    review_deadline: review ? utcDate(review) : null,
    items: items.map((i) => ({
      problem_version_id: i.problem_version_id,
      test_suite_id: i.test_suite_id,
      rubric_id: i.rubric_id,
      max_score: i.max_score,
      score_weight: i.score_weight,
      required_reviewers: i.required_reviewers,
    })),
    student_ids: [...studentIds],
  };
}
export function equalWeights(items: AssignmentItem[]) {
  if (!items.length) return;
  const part = Math.floor(1_000_000 / items.length);
  items.forEach((item, index) => {
    item.score_weight = (
      (index === items.length - 1 ? 1_000_000 - part * index : part) / 1_000_000
    ).toFixed(6);
  });
}
export const assignmentStates = {
  DRAFT: "草稿",
  OPEN: "开放提交",
  CLOSED: "已关闭提交",
} as const;
