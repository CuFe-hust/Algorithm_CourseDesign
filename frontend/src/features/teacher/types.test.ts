import { it, expect } from "vitest";
import { editable, newVersion, type Version } from "./types";
it("projects a strict write DTO without reference/config metadata or ID precision loss", () => {
  const value = {
    ...newVersion(),
    knowledge_point_ids: ["9223372036854775806"],
    reference_solutions: [{ id: "99", language: null, content: "answer" }],
    rubric: { id: "9", name: "评分量表", items: [] },
    id: "100",
    version_no: 3,
  } as unknown as Version;
  const result = editable(value);
  expect(result.knowledge_point_ids).toEqual(["9223372036854775806"]);
  expect(result).not.toHaveProperty("id");
  expect(result.rubric).not.toHaveProperty("id");
  expect(result.reference_solutions[0]).not.toHaveProperty("id");
  result.knowledge_point_ids.push("2");
  expect(value.knowledge_point_ids).toHaveLength(1);
});
