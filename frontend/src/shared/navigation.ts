import type { Course } from "./session";

const STUDENT_PREFIX = "/student/courses/";
const TEACHER_PREFIX = "/teacher";

/** Accept only same-origin, path-only targets. Anything else is dropped. */
export function safeInternalPath(raw: string | null | undefined): string {
  const value = (raw || "").trim();
  if (!value.startsWith("/")) return "";
  if (value.startsWith("//")) return ""; // protocol-relative URL
  if (value.includes("\\") || value.includes("\n") || value.includes("\r"))
    return "";
  return value;
}

export function courseHome(course: Course): string {
  return course.role === "TEACHER"
    ? "/teacher"
    : `/student/courses/${course.id}`;
}

/**
 * Where to go after the user explicitly picks a course.
 *
 * The return location is honoured only when it belongs to the course that was
 * actually selected. A deep link into another course, or a teacher page picked
 * from a student course, falls back to that course's home instead of leaking
 * access or bouncing the user back to the course picker.
 */
export function courseEntryTarget(next: string, course: Course): string {
  const path = safeInternalPath(next);
  const home = courseHome(course);
  if (!path || path === "/courses" || path === "/login" || path === "/")
    return home;
  if (path.startsWith(STUDENT_PREFIX)) {
    const targetCourseId = path.slice(STUDENT_PREFIX.length).split(/[/?#]/)[0];
    return course.role === "STUDENT" && targetCourseId === course.id
      ? path
      : home;
  }
  if (path === TEACHER_PREFIX || path.startsWith(`${TEACHER_PREFIX}/`)) {
    return course.role === "TEACHER" ? path : home;
  }
  return home;
}
