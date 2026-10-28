/** Types for the teacher-facing similarity evidence view. */

export interface SimilarityPerson {
  submission_id: string;
  student_id: string | null;
  student_no: string | null;
  name: string | null;
  version_no: number | null;
}

export interface SimilaritySpan {
  left_start_line: number;
  left_end_line: number;
  right_start_line: number;
  right_end_line: number;
  matched_tokens: number;
  run_tokens: number;
}

export interface SimilarityPair {
  left: SimilarityPerson;
  right: SimilarityPerson;
  similarity: string;
  jaccard: string | null;
  containment_left: string | null;
  containment_right: string | null;
  shared_fingerprints: number | null;
  matched_tokens: number | null;
  longest_run_tokens: number | null;
  spans: SimilaritySpan[];
}

export interface SimilarityCluster {
  members: SimilarityPerson[];
  size: number;
  max_similarity: string;
}

export interface SimilarityInsufficient {
  submission: SimilarityPerson;
  reason: string;
  tokens: number | null;
}

export interface SimilarityItem {
  item_id: string;
  problem_code: string | null;
  title: string | null;
  status: string;
  business_status: string | null;
  submission_count: number;
  implementation_name: string;
  implementation_version: string;
  method: string | null;
  parameters: Record<string, string | number> | null;
  /** True when the pair list hit the 500-pair cap; clusters remain complete. */
  pairs_truncated: boolean;
  pairs: SimilarityPair[];
  clusters: SimilarityCluster[];
  insufficient: SimilarityInsufficient[];
}

export interface SimilarityEvidence {
  batch_id: string;
  assignment_id: string | null;
  status: string;
  threshold: string | null;
  items: SimilarityItem[];
  limitations: string[];
}

export interface SimilarityScopeItem {
  item_id: string;
  problem_code: string;
  title: string;
  submitted_students: number;
}

export interface SimilarityScopeAssignment {
  id: string;
  title: string;
  submission_status: string;
  submission_deadline: string;
  deadline_passed: boolean;
  items: SimilarityScopeItem[];
}

export const insufficientLabels: Record<string, string> = {
  INSUFFICIENT_TOKENS: "代码过短，不参与比较",
  NOT_A_PROGRAMMING_LANGUAGE: "不是可比较的编程语言",
  TOKENIZATION_FAILED: "代码无法词法切分",
};

export function personLabel(person: SimilarityPerson): string {
  return person.name || person.student_no || person.submission_id;
}

export function percent(value: string | number | null | undefined): string {
  // null/undefined/"" must not render as 0.0%: missing evidence is not zero.
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${(number * 100).toFixed(1)}%`;
}
