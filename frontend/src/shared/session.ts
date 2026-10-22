import { reactive } from "vue";
import { clearSession, post, request } from "./api";
export interface Course {
  id: string;
  name: string;
  term: string;
  role: "TEACHER" | "STUDENT";
}
export interface User {
  id: string;
  login_name: string;
  full_name: string;
}
function storedUser(): User | null {
  try {
    return JSON.parse(sessionStorage.getItem("algoclass.user") || "null");
  } catch {
    return null;
  }
}
export const session = reactive({
  user: storedUser(),
  courses: [] as Course[],
  courseId: sessionStorage.getItem("algoclass.teacher-course") || "",
});
export async function loadCourses() {
  const result = await request<{ items: Course[] }>("/courses");
  session.courses = result.items;
  if (
    !result.items.some((c) => c.id === session.courseId && c.role === "TEACHER")
  )
    selectCourse(result.items.find((c) => c.role === "TEACHER")?.id || "");
}
export function selectCourse(id: string) {
  session.courseId = id;
  sessionStorage.setItem("algoclass.teacher-course", id);
}
export async function login(login_name: string, password: string) {
  const data = await post<{ access_token: string; user: User }>("/auth/login", {
    login_name,
    password,
  });
  sessionStorage.setItem("algoclass.token", data.access_token);
  sessionStorage.setItem("algoclass.user", JSON.stringify(data.user));
  session.user = data.user;
  await loadCourses();
}
export async function logout() {
  try {
    await post("/auth/logout");
  } finally {
    clearSession();
    session.user = null;
    session.courses = [];
    selectCourse("");
  }
}
