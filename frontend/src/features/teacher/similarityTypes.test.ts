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

  it("gives every skip reason its own explanation", () => {
    // Exact strings, not toBeTruthy: a degenerate label such as "过短" passed the
    // old assertion, so the test could not notice the text being gutted.
    expect(insufficientLabels.INSUFFICIENT_TOKENS).toBe("代码过短，不参与比较");
    expect(insufficientLabels.NOT_A_PROGRAMMING_LANGUAGE).toBe(
      "不是可比较的编程语言",
    );
    expect(insufficientLabels.TOKENIZATION_FAILED).toBe("代码无法词法切分");
    expect(new Set(Object.values(insufficientLabels)).size).toBe(
      Object.keys(insufficientLabels).length,
    );
  });
});
