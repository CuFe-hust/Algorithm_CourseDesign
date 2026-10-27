import { describe, expect, it } from "vitest";
import { insufficientLabels, percent, personLabel } from "./similarityTypes";

describe("similarity presentation helpers", () => {
  it("prefers the real name, then the student number, then the id", () => {
    expect(
      personLabel({
        submission_id: "1",
        student_id: "2",
        student_no: "S1",
        name: "张三",
        version_no: 1,
      }),
    ).toBe("张三");
    expect(
      personLabel({
        submission_id: "1",
        student_id: "2",
        student_no: "S1",
        name: null,
        version_no: 1,
      }),
    ).toBe("S1");
    expect(
      personLabel({
        submission_id: "9",
        student_id: null,
        student_no: null,
        name: null,
        version_no: 1,
      }),
    ).toBe("9");
  });

  it("formats a ratio without inventing a value for missing data", () => {
    expect(percent("0.793103")).toBe("79.3%");
    expect(percent(1)).toBe("100.0%");
    expect(percent(null)).toBe("—");
  });

  it("labels every skip reason the backend can send", () => {
    expect(insufficientLabels.INSUFFICIENT_TOKENS).toContain("过短");
    expect(insufficientLabels.NOT_A_PROGRAMMING_LANGUAGE).toBeTruthy();
    expect(insufficientLabels.TOKENIZATION_FAILED).toBeTruthy();
  });
});
