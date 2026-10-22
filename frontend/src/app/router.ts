import { createRouter, createWebHistory } from "vue-router";
import { token } from "../shared/api";
import { loadCourses, session } from "../shared/session";
import Login from "../shared/Login.vue";
import TeacherLayout from "../features/teacher/TeacherLayout.vue";
export const teacherRoutes = [
  {
    path: "",
    name: "teacher-home",
    component: () => import("../features/teacher/Overview.vue"),
  },
  {
    path: "problems",
    name: "teacher-problems",
    component: () => import("../features/teacher/Problems.vue"),
  },
  {
    path: "problems/new",
    name: "teacher-problem-new",
    component: () => import("../features/teacher/ProblemEditor.vue"),
  },
  {
    path: "problems/:id",
    name: "teacher-problem-edit",
    component: () => import("../features/teacher/ProblemEditor.vue"),
  },
  {
    path: "students",
    name: "teacher-students",
    component: () => import("../features/teacher/Students.vue"),
  },
  {
    path: "students/import",
    name: "teacher-student-import",
    component: () => import("../features/teacher/StudentImport.vue"),
  },
];
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: Login },
    { path: "/teacher", component: TeacherLayout, children: teacherRoutes },
    { path: "/access", component: () => import("../shared/Access.vue") },
    { path: "/", redirect: "/teacher" },
    {
      path: "/:pathMatch(.*)*",
      component: () => import("../shared/NotFound.vue"),
    },
  ],
});
router.beforeEach(async (to) => {
  if (to.path === "/login") return true;
  if (!token()) return { path: "/login", query: { next: to.fullPath } };
  if (to.path.startsWith("/teacher")) {
    try {
      await loadCourses();
    } catch {
      return "/login";
    }
    if (!session.courses.some((c) => c.role === "TEACHER")) return "/access";
  }
});
window.addEventListener("session-expired", () => {
  void router.replace("/login");
});
export default router;
