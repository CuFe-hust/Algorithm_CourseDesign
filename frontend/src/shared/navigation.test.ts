import { describe, expect, it } from "vitest";
import { courseEntryTarget, courseHome, safeInternalPath } from "./navigation";
import type { Course } from "./session";

const studentCourse: Course = {
  id: "7",
  name: "算法",
  term: "2026-1",
  role: "STUDENT",
};
const teacherCourse: Course = {
  id: "9",
  name: "算法",
  term: "2026-1",
  role: "TEACHER",
};

describe("login return location (R02 / AC01)", () => {
  it("keeps only same-origin paths", () => {
    expect(safeInternalPath("/student/courses/7")).toBe("/student/courses/7");
    expect(safeInternalPath("//evil.example/x")).toBe("");
    expect(safeInternalPath("https://evil.example")).toBe("");
    expect(safeInternalPath("javascript:alert(1)")).toBe("");
    expect(safeInternalPath("/a\\b")).toBe("");
    expect(safeInternalPath(undefined)).toBe("");
  });

  it("falls back to the selected course home without a return location", () => {
    expect(courseEntryTarget("", studentCourse)).toBe("/student/courses/7");
    expect(courseEntryTarget("/courses", studentCourse)).toBe(
      "/student/courses/7",
    );
    expect(courseHome(teacherCourse)).toBe("/teacher");
  });

  it("resumes a deep link only inside the course that was selected", () => {
    expect(
      courseEntryTarget(
        "/student/courses/7/assignments/3/items/5",
        studentCourse,
      ),
    ).toBe("/student/courses/7/assignments/3/items/5");
    // A different course must not be reachable by reusing someone else's link.
    expect(
      courseEntryTarget(
        "/student/courses/99/assignments/3/items/5",
        studentCourse,
      ),
    ).toBe("/student/courses/7");
    expect(
      courseEntryTarget("/student/courses/7/submissions/11", teacherCourse),
    ).toBe("/teacher");
  });

  it("does not send a student course into the teacher workspace", () => {
    expect(courseEntryTarget("/teacher/problems", studentCourse)).toBe(
      "/student/courses/7",
    );
    expect(courseEntryTarget("/teacher/problems", teacherCourse)).toBe(
      "/teacher/problems",
    );
    expect(courseEntryTarget("/student/courses/7", teacherCourse)).toBe(
      "/teacher",
    );
  });
});
