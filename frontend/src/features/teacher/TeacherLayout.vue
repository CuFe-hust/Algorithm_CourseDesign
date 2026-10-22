<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import {
  BookOpen,
  LayoutDashboard,
  LibraryBig,
  Users,
  LogOut,
  ChevronDown,
  Menu,
  GraduationCap,
} from "@lucide/vue";
import { session, selectCourse, logout } from "../../shared/session";
import { errorText } from "../../shared/api";
const router = useRouter(),
  mobile = ref(false),
  error = ref("");
const course = computed(() =>
  session.courses.find((c) => c.id === session.courseId),
);
async function changeCourse(event: Event) {
  const id = (event.target as HTMLSelectElement).value;
  // Navigate first: an editor's unsaved-change guard can cancel the switch.
  await router.push("/teacher");
  if (router.currentRoute.value.path === "/teacher") selectCourse(id);
}
async function leave() {
  await router.push("/login");
  if (router.currentRoute.value.path !== "/login") return;
  try {
    await logout();
  } catch (e) {
    error.value = errorText(e);
  }
}
</script>
<template>
  <div class="workspace">
    <aside class="sidebar" :class="{ open: mobile }">
      <RouterLink to="/teacher" class="brand"
        ><span class="brand-icon"><BookOpen :size="22" /></span
        >AlgoClass</RouterLink
      >
      <div class="workspace-label">教师工作台 <span>TEACHER</span></div>
      <nav aria-label="主导航" @click="mobile = false">
        <RouterLink
          to="/teacher"
          exact-active-class="selected"
          :class="{ selected: $route.path === '/teacher' }"
          ><LayoutDashboard :size="19" />课程概览</RouterLink
        ><RouterLink
          to="/teacher/problems"
          :class="{ selected: $route.path.startsWith('/teacher/problems') }"
          ><LibraryBig :size="19" />题库管理</RouterLink
        ><RouterLink
          to="/teacher/students"
          :class="{ selected: $route.path.startsWith('/teacher/students') }"
          ><Users :size="19" />学生名单</RouterLink
        >
      </nav>
      <div class="sidebar-foot">
        <GraduationCap :size="22" /><strong>算法设计与分析</strong>
        <p>备好每一题，关注每一次成长。</p>
      </div>
    </aside>
    <div v-if="mobile" class="scrim" @click="mobile = false"></div>
    <div class="main-shell">
      <header class="topbar">
        <button
          class="icon-button mobile-menu"
          aria-label="展开导航"
          @click="mobile = !mobile"
        >
          <Menu :size="22" />
        </button>
        <div class="course-select">
          <span class="small-label">当前课程</span>
          <div>
            <select
              :value="session.courseId"
              aria-label="当前课程"
              @change="changeCourse"
            >
              <option
                v-for="c in session.courses.filter((c) => c.role === 'TEACHER')"
                :key="c.id"
                :value="c.id"
              >
                {{ c.name }} · {{ c.term }}
              </option></select
            ><ChevronDown :size="15" />
          </div>
        </div>
        <div class="account">
          <span class="avatar">{{
            session.user?.full_name?.slice(-2) || "教师"
          }}</span
          ><span
            ><strong>{{ session.user?.full_name }}</strong
            ><small>任课教师</small></span
          ><button
            class="icon-button"
            aria-label="退出登录"
            title="退出登录"
            @click="leave"
          >
            <LogOut :size="18" />
          </button>
        </div>
      </header>
      <main class="page">
        <div v-if="error" class="alert error">{{ error }}</div>
        <RouterView :key="`${session.courseId}:${$route.path}`" />
      </main>
      <footer class="page-footer">
        AlgoClass · {{ course?.term }}<span>算法课程教学工作台</span>
      </footer>
    </div>
  </div>
</template>
