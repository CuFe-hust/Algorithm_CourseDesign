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
  left_tokens: number | null;
  right_tokens: number | null;
  matched_tokens: number | null;
  longest_run_tokens: number | null;
  spans: SimilaritySpan[];
}

/**
 * Evidence strength depends on program length. On short, formulaic programs the
 * problem statement dictates most of the token stream: measured on this codebase,
 * independent implementations of one standard algorithm with a shared classroom
 * I/O idiom score 0.54 to 1.00 below ~120 tokens, and two different algorithms
 * sharing only the input idiom score 0.86. Below this size a high score says
 * little about copying.
 */
const WEAK_EVIDENCE_TOKENS = 120;

export function weakEvidence(pair: SimilarityPair): boolean {
  const smallest = Math.min(
    pair.left_tokens ?? Infinity,
    pair.right_tokens ?? Infinity,
  );
  return smallest < WEAK_EVIDENCE_TOKENS;
}

/** Same-problem pairs of genuinely different algorithms reach this band. */
export function ambiguousBand(
  similarity: string | number | null | undefined,
): boolean {
  const value = Number(similarity);
  return Number.isFinite(value) && value >= 0.5 && value < 0.7;
}

export interface SimilarityCluster {
  members: SimilarityPerson[];
  size: number;
  max_similarity: string;
  min_similarity: string | null;
  qualifying_pairs: number | null;
  total_pairs: number | null;
}

/** A cluster is a connected component, not a clique; chains look like this. */
export function clusterIsChain(cluster: SimilarityCluster): boolean {
  return (
    cluster.qualifying_pairs !== null &&
    cluster.total_pairs !== null &&
    cluster.qualifying_pairs < cluster.total_pairs
  );
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
  /** Submission counts per language; cross-language pairs are never compared. */
  language_counts: Record<string, number> | null;
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
