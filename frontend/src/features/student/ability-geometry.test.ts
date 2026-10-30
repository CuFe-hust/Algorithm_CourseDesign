import { describe, expect, it } from "vitest";
import {
  percent,
  radarGeometry,
  radarPoint,
  scoreValue,
  visibleChapters,
  type AbilityEstimate,
} from "./ability";

function chapter(
  index: number,
  overrides: Partial<AbilityEstimate> = {},
): AbilityEstimate {
  return {
    object_key: "student:1",
    dimension: `CH${String(index).padStart(2, "0")}`,
    dimension_label: `第 ${index} 章`,
    dimension_order: index,
    value: "0.5",
    status: "OK",
    n_items: 2,
    assigned_items: 4,
    scored_items: 2,
    W_sum: "2",
    n_eff: "2",
    coverage_items: "0.5",
    coverage_weight: "0.5",
    missing: { pending: 1, not_submitted: 1, invalid: 0 },
    observed_min: "0",
    observed_max: "1",
    diagnostic_flags: [],
    by_type: {
      PROGRAMMING: { value: "0", n_items: 1, W_sum: "1" },
      SUBJECTIVE: { value: "1", n_items: 1, W_sum: "1" },
    },
    ...overrides,
  };
}
describe("chapter display policy", () => {
  it("hides uncovered chapters, preserves no-evidence chapters and orders without mutating the source", () => {
    const input = [
      chapter(11),
      chapter(1, { status: "NOT_COVERED" }),
      chapter(3, { status: "NO_EVIDENCE", value: null }),
    ];
    expect(visibleChapters(input).map((item) => item.dimension)).toEqual([
      "CH03",
      "CH11",
    ]);
    expect(input[0]?.dimension).toBe("CH11");
  });
  it("preserves scored zero and never converts missing or invalid evidence to zero", () => {
    expect(scoreValue(chapter(1, { value: "0.0000" }))).toBe(0);
    for (const value of [null, "", "NaN", "-0.1", "1.1"])
      expect(scoreValue(chapter(1, { value }))).toBeNull();
    expect(
      scoreValue(chapter(1, { status: "NO_EVIDENCE", value: "0" })),
    ).toBeNull();
    expect(percent(null)).toBe("—");
    expect(percent(0)).toBe("0.0%");
  });
});
describe("radar geometry", () => {
  it("uses the same 0–1 radius for every chapter, including real zero", () => {
    expect(radarPoint(0, 4, 0)).toEqual({ x: 220, y: 205 });
    expect(radarPoint(0, 4, 1)).toEqual({ x: 220, y: 73 });
    expect(radarPoint(1, 4, 0.5)).toEqual({ x: 286, y: 205 });
  });
  it("leaves gaps around missing chapters rather than closing across them", () => {
    const geometry = radarGeometry([
      chapter(1),
      chapter(2, { status: "NO_EVIDENCE", value: null }),
      chapter(3),
      chapter(4),
    ]);
    expect(geometry.points[1]?.position).toBeNull();
    expect(geometry.segments).toHaveLength(2);
    expect(geometry.segments[0]?.from).toEqual(geometry.points[2]?.position);
    expect(geometry.segments[0]?.to).toEqual(geometry.points[3]?.position);
    expect(geometry.segments[1]?.to).toEqual(geometry.points[0]?.position);
  });
  it("does not connect across multiple missing chapters and uses no polygon for fewer than three axes", () => {
    expect(
      radarGeometry([
        chapter(1),
        chapter(2, { value: null }),
        chapter(3),
        chapter(4, { value: null }),
      ]).segments,
    ).toHaveLength(0);
    expect(radarGeometry([chapter(1), chapter(2)]).segments).toHaveLength(0);
    expect(radarGeometry([]).segments).toEqual([]);
  });
});
