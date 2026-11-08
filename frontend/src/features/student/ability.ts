import { request } from "../../shared/api";

type Decimal = string | number;
export type AbilityModel = "b0" | "d1";
export interface AbilityEstimate {
  object_key: string;
  dimension: string;
  dimension_label: string;
  dimension_order: number;
  value: Decimal | null;
  baseline_value?: Decimal | null;
  theta?: Decimal | null;
  score_semantics?: "REFERENCE_EXPECTED_SCORE";
  status: "NOT_COVERED" | "NO_EVIDENCE" | "LOW_EVIDENCE" | "OK";
  n_items: number;
  assigned_items: number;
  scored_items: number;
  W_sum: Decimal;
  n_eff: Decimal;
  coverage_items: Decimal | null;
  coverage_weight: Decimal | null;
  missing: { pending: number; not_submitted: number; invalid: number };
  observed_min: Decimal | null;
  observed_max: Decimal | null;
  diagnostic_flags: string[];
  by_type: Partial<
    Record<
      "PROGRAMMING" | "SUBJECTIVE",
      {
        value: Decimal | null;
        n_items: number;
        W_sum: Decimal;
      }
    >
  >;
}
export interface AbilityReport {
  status:
    | "OK"
    | "NO_REAL_ANALYSIS"
    | "NO_DEMO_ANALYSIS"
    | "INSUFFICIENT_DATA"
    | "ANALYSIS_PENDING"
    | "ANALYSIS_FAILED"
    | "NOT_IN_SCOPE";
  course_id: string;
  batch_id?: string;
  reason?: string;
  computed_at?: string;
  is_mock: boolean;
  source_kind: string;
  results_snapshot_version?: string;
  scoring_policy_version?: string;
  chapter_mapping_version?: string;
  implementation_version?: string;
  scope_label?: string;
  assignment_count?: number;
  method?: "B0" | "DIFFICULTY_FRACTIONAL";
  model_parameters?: {
    learner_l2: Decimal;
    item_l2: Decimal;
    difficulty_scale: Decimal;
    max_iterations: number;
    tolerance: Decimal;
    calibrate_items?: boolean;
  };
  model_diagnostics?: {
    loss: Decimal;
    iterations: number;
    converged: boolean;
    score_semantics: "REFERENCE_EXPECTED_SCORE";
    difficulty_source:
      "TEACHER_PRIOR_WITH_COHORT_CALIBRATION" | "FIXED_TEACHER_PRIOR";
  };
  process_diagnostics?: {
    available: boolean;
    items: {
      item_key: string;
      submission_count: number;
      first_score: Decimal | null;
      latest_score: Decimal | null;
      best_score: Decimal | null;
      first_accepted_attempt: number | null;
      repeated_failure_pairs: number;
    }[];
  };
  estimates: AbilityEstimate[];
}

export function myAbility(
  courseId: string,
  demo = false,
  model: AbilityModel = "b0",
) {
  return request<AbilityReport>(
    `/courses/${encodeURIComponent(courseId)}/my-ability${model === "d1" ? "/difficulty" : ""}${demo ? "/demo" : ""}`,
  );
}

export function visibleChapters(estimates: AbilityEstimate[]) {
  return estimates
    .filter((item) => item.status !== "NOT_COVERED")
    .sort(
      (a, b) =>
        a.dimension_order - b.dimension_order ||
        a.dimension.localeCompare(b.dimension),
    );
}

/** Missing evidence is never a score; preserve an actual scored zero. */
export function scoreValue(
  item: Pick<AbilityEstimate, "value" | "status">,
): number | null {
  if (
    item.status === "NO_EVIDENCE" ||
    item.status === "NOT_COVERED" ||
    item.value == null ||
    item.value === ""
  )
    return null;
  const value = Number(item.value);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

export function percent(value: Decimal | null | undefined): string {
  if (value == null || value === "" || !Number.isFinite(Number(value)))
    return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

export function baselineValue(item: AbilityEstimate): number | null {
  return scoreValue({
    value: item.baseline_value ?? null,
    status: item.status,
  });
}

export function percentagePointDifference(item: AbilityEstimate): string {
  const value = scoreValue(item);
  const baseline = baselineValue(item);
  if (value === null || baseline === null) return "—";
  const difference = Number(((value - baseline) * 100).toFixed(1));
  return `${difference > 0 ? "+" : difference < 0 ? "−" : ""}${Math.abs(difference).toFixed(1)} 个百分点`;
}

export const statusLabel = {
  NOT_COVERED: "未覆盖",
  NO_EVIDENCE: "暂无有效证据",
  LOW_EVIDENCE: "证据较少",
  OK: "有有效证据",
};

export function radarPoint(
  index: number,
  count: number,
  value: number,
  radius = 132,
) {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count;
  return {
    x: 220 + Math.cos(angle) * radius * value,
    y: 205 + Math.sin(angle) * radius * value,
  };
}

export function radarGeometry(chapters: AbilityEstimate[]) {
  const points = chapters.map((chapter, index) => {
    const value = scoreValue(chapter);
    return {
      chapter,
      value,
      position:
        value == null ? null : radarPoint(index, chapters.length, value),
    };
  });
  // Only adjacent observed chapters form an edge. A missing chapter leaves a gap.
  const segments = points.flatMap((point, index) => {
    const next = points[(index + 1) % points.length];
    return point.position && next?.position && points.length >= 3
      ? [{ from: point.position, to: next.position }]
      : [];
  });
  return { points, segments };
}
