import { createRouter, createWebHistory } from "vue-router";
import { token } from "../shared/api";
import {
  loadCourses,
  loadSession,
  resetLocalSession,
  selectCourse,
  session,
} from "../shared/session";
import Login from "../shared/Login.vue";
import TeacherLayout from "../features/teacher/TeacherLayout.vue";
import StudentLayout from "../features/student/StudentLayout.vue";
import {
  startActivityTracking,
  stopActivityTracking,
} from "../shared/activity";

export const teacherRoutes = [
  {
    path: "analysis",
    name: "teacher-analysis",
    component: () => import("../features/analytics/AnalysisCenter.vue"),
  },
  {
    path: "results",
    name: "teacher-results",
    component: () => import("../features/analytics/Results.vue"),
  },
  {
    path: "reviews",
    name: "teacher-reviews",
    component: () =>
      import("../features/analytics/peer-review/TeacherRounds.vue"),
  },
  {
    path: "reviews/:id",
    name: "teacher-review",
    component: () =>
      import("../features/analytics/peer-review/TeacherRound.vue"),
  },
  {
    path: "assignments",
    name: "teacher-assignments",
    component: () => import("../features/teacher/Assignments.vue"),
  },
  {
    path: "assignments/new",
    name: "teacher-assignment-new",
    component: () => import("../features/teacher/AssignmentEditor.vue"),
  },
  {
    path: "assignments/:id",
    name: "teacher-assignment-edit",
    component: () => import("../features/teacher/AssignmentEditor.vue"),
  },
  {
    path: "complexity",
    name: "teacher-complexity",
    component: () => import("../features/teacher/Complexity.vue"),
  },
  {
    path: "students/:studentId/progress",
    name: "teacher-student-progress",
    component: () => import("../features/teacher/StudentProgress.vue"),
  },
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
    path: "similarity",
    name: "teacher-similarity",
    component: () => import("../features/teacher/Similarity.vue"),
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

export const studentRoutes = [
  {
    path: "learning",
    name: "student-learning",
    component: () => import("../features/analytics/Results.vue"),
  },
  {
    path: "reviews",
    name: "student-reviews",
    component: () =>
      import("../features/analytics/peer-review/StudentTasks.vue"),
  },
  {
    path: "reviews/:taskId",
    name: "student-review",
    component: () =>
      import("../features/analytics/peer-review/StudentTask.vue"),
  },
  {
    path: "ability",
    name: "student-ability",
    component: () => import("../features/student/Ability.vue"),
  },
  {
    path: "",
    name: "student-home",
    component: () => import("../features/student/CourseHome.vue"),
  },
  {
    path: "assignments/:assignmentId",
    name: "student-assignment",
    component: () => import("../features/student/AssignmentDetail.vue"),
  },
  {
    path: "assignments/:assignmentId/items/:itemId",
    name: "student-answer",
    component: () => import("../features/student/AnswerWorkspace.vue"),
  },
  {
    path: "submissions",
    name: "student-submissions",
    component: () => import("../features/student/SubmissionHistory.vue"),
  },
  {
    path: "submissions/:submissionId",
    name: "student-submission",
    component: () => import("../features/student/SubmissionDetail.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: Login },
    { path: "/courses", component: () => import("../shared/CourseSelect.vue") },
    {
      path: "/account/change-password",
      component: () => import("../shared/ChangePassword.vue"),
    },
    { path: "/teacher", component: TeacherLayout, children: teacherRoutes },
    {
      path: "/student/courses/:courseId",
      component: StudentLayout,
      children: studentRoutes,
    },
    { path: "/access", component: () => import("../shared/Access.vue") },
    { path: "/", component: () => import("../shared/CourseSelect.vue") },
    {
      path: "/:pathMatch(.*)*",
      component: () => import("../shared/NotFound.vue"),
    },
  ],
});

async function ensureSession() {
  if (session.ready && session.user) return true;
  try {
    await loadSession();
    return true;
  } catch {
    return false;
  }
}

router.beforeEach(async (to) => {
  if (to.path === "/login") return true;
  if (!token()) return { path: "/login", query: { next: to.fullPath } };
  if (!(await ensureSession()))
    return { path: "/login", query: { next: to.fullPath } };
  if (session.mustChangePassword && to.path !== "/account/change-password") {
    return { path: "/account/change-password", query: { next: to.fullPath } };
  }
  if (to.path === "/account/change-password") return true;
  if (!session.coursesLoaded) {
    try {
      await loadCourses();
    } catch {
      return { path: "/login", query: { next: to.fullPath } };
    }
  }
  if (to.path.startsWith("/student/courses/")) {
    const courseId = String(to.params.courseId);
    const course = session.courses.find((entry) => entry.id === courseId);
    if (!course || course.role !== "STUDENT") return "/access";
    if (session.courseId !== courseId) selectCourse(courseId);
    return true;
  }
  if (to.path.startsWith("/teacher")) {
    if (!session.courses.some((entry) => entry.role === "TEACHER"))
      return "/access";
    const current = session.courses.find(
      (entry) => entry.id === session.courseId,
    );
    if (!current || current.role !== "TEACHER") {
      return { path: "/courses", query: { next: to.fullPath } };
    }
    return true;
  }
  if (to.path === "/" || to.path === "/courses") {
    if (to.path === "/courses") return true;
    const course = session.courses.find(
      (entry) => entry.id === session.courseId,
    );
    if (!course) return "/courses";
    return course.role === "TEACHER"
      ? "/teacher"
      : `/student/courses/${course.id}`;
  }
  return true;
});

window.addEventListener("session-expired", () => {
  stopActivityTracking();
  resetLocalSession();
  void router.replace({
    path: "/login",
    query: { next: router.currentRoute.value.fullPath },
  });
});

router.afterEach((to) => {
  if (token() && session.user && to.path !== "/login") startActivityTracking();
  else stopActivityTracking();
});

export default router;
