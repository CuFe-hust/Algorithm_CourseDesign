export const typeNames = {
  PROGRAMMING: "编程题",
  ALGORITHM_ANALYSIS: "算法分析题",
  PROOF: "证明题",
  OPEN_QUESTION: "开放性问答题",
} as const;
export type QuestionType = keyof typeof typeNames;
export interface VersionInput {
  title: string;
  statement_md: string;
  answer_requirements_md: string | null;
  input_spec_md: string | null;
  output_spec_md: string | null;
  data_constraints_md: string | null;
  public_examples_md: string | null;
  difficulty_level: number;
  source_reference: string | null;
  knowledge_point_ids: string[];
  reference_solutions: { language: string | null; content: string }[];
  test_suite: {
    cpu_limit_ms: number;
    memory_limit_kib: number;
    allowed_languages: string[];
    checker: "TEXT_TRIM_TRAILING";
    cases: {
      input_text: string;
      expected_output: string;
      weight: string;
      is_public: boolean;
    }[];
  } | null;
  rubric: {
    name: string;
    items: { name: string; description: string; max_score: string }[];
  } | null;
}
export interface Version extends VersionInput {
  id: string;
  problem_id: string;
  course_id: string;
  code: string;
  question_type: QuestionType;
  problem_status: string;
  version_no: number;
  status: "DRAFT" | "FROZEN";
  updated_at: string;
  frozen_at: string | null;
}
export interface Problem {
  id: string;
  code: string;
  course_id: string;
  question_type: QuestionType;
  status: string;
  latest_version: Version;
  versions: Pick<
    Version,
    "id" | "version_no" | "title" | "status" | "updated_at"
  >[];
}
export interface Page<T> {
  total: number;
  items: T[];
  limit: number;
  offset: number;
}
export function newVersion(programming = false): VersionInput {
  return {
    title: "",
    statement_md: "",
    answer_requirements_md: "",
    input_spec_md: "",
    output_spec_md: "",
    data_constraints_md: "",
    public_examples_md: "",
    difficulty_level: 3,
    source_reference: "",
    knowledge_point_ids: [],
    reference_solutions: [],
    test_suite: programming
      ? {
          cpu_limit_ms: 1000,
          memory_limit_kib: 262144,
          allowed_languages: ["python3"],
          checker: "TEXT_TRIM_TRAILING",
          cases: [],
        }
      : null,
    rubric: programming ? null : { name: "评分量表", items: [] },
  };
}
// Explicit projection prevents server metadata being echoed into strict write DTOs.
export function editable(v: VersionInput): VersionInput {
  const out = newVersion(Boolean(v.test_suite));
  for (const key of [
    "title",
    "statement_md",
    "answer_requirements_md",
    "input_spec_md",
    "output_spec_md",
    "data_constraints_md",
    "public_examples_md",
    "difficulty_level",
    "source_reference",
    "knowledge_point_ids",
  ] as const)
    (out as unknown as Record<string, unknown>)[key] = structuredClone(v[key]);
  out.reference_solutions = v.reference_solutions.map((r) => ({
    language: r.language,
    content: r.content,
  }));
  out.test_suite = v.test_suite
    ? {
        cpu_limit_ms: v.test_suite.cpu_limit_ms,
        memory_limit_kib: v.test_suite.memory_limit_kib,
        allowed_languages: [...v.test_suite.allowed_languages],
        checker: v.test_suite.checker,
        cases: v.test_suite.cases.map((c) => ({ ...c })),
      }
    : null;
  out.rubric = v.rubric
    ? { name: v.rubric.name, items: v.rubric.items.map((i) => ({ ...i })) }
    : null;
  return out;
}
export const dateText = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
