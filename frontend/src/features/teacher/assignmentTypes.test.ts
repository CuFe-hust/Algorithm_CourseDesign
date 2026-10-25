import { expect, it } from "vitest";
import {
  assignmentPayload,
  equalWeights,
  localDate,
  utcDate,
  type AssignmentItem,
} from "./assignmentTypes";
it("keeps exact six-place weights summing to one for three questions", () => {
  const items = Array.from({ length: 3 }, () => ({
    score_weight: "1",
  })) as AssignmentItem[];
  equalWeights(items);
  expect(items.map((i) => i.score_weight)).toEqual([
    "0.333333",
    "0.333333",
    "0.333334",
  ]);
});
it("projects pinned IDs and scores without server metadata or BIGINT coercion", () => {
  const item = {
    problem_version_id: "9223372036854775806",
    test_suite_id: "9223372036854775805",
    rubric_id: null,
    max_score: "100.00",
    score_weight: "1.000000",
    required_reviewers: 0,
    id: "123",
    title: "sample",
  } as AssignmentItem;
  const value = assignmentPayload(
    " test ",
    "description",
    "2026-11-01T20:30",
    "",
    [item],
    ["9223372036854775804"],
  );
  expect(value.title).toBe("test");
  expect(value.items[0]).not.toHaveProperty("id");
  expect(value.items[0]).not.toHaveProperty("title");
  expect(value.items[0]!.problem_version_id).toBe(item.problem_version_id);
  expect(value.student_ids[0]).toBe("9223372036854775804");
  expect(localDate(value.submission_deadline)).toBe("2026-11-01T20:30");
  expect(value.review_deadline).toBeNull();
});
it("rejects empty or invalid dates before sending a write", () => {
  expect(() => utcDate("")).toThrow();
  expect(() => utcDate("invalid")).toThrow();
});
