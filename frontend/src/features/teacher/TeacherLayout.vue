<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Activity,
  BookOpen,
  ChartNoAxesCombined,
  LayoutDashboard,
  LibraryBig,
  Users,
  LogOut,
  ChevronDown,
  Menu,
  ClipboardList,
  Layers,
} from "@lucide/vue";
import { session, selectCourse, logout } from "../../shared/session";
import { errorText } from "../../shared/api";
const router = useRouter(),
  mobile = ref(false),
  error = ref(""),
  switchingCourse = ref(false);
const course = computed(() =>
  session.courses.find((c) => c.id === session.courseId),
);
async function changeCourse(event: Event) {
  const select = event.target as HTMLSelectElement;
  const id = select.value;
  if (switchingCourse.value) {
    select.value = session.courseId;
    return;
  }
  switchingCourse.value = true;
  // Navigate first: an editor's unsaved-change guard can cancel the switch.
  try {
    await router.push("/teacher");
    if (router.currentRoute.value.path === "/teacher") selectCourse(id);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    // Native selects change before Vue's route guard resolves. Restore their
    // displayed value after cancellation, even if reactive state never changed.
    select.value = session.courseId;
    switchingCourse.value = false;
  }
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
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <aside id="teacher-sidebar" class="sidebar" :class="{ open: mobile }">
      <RouterLink to="/teacher" class="brand"
        ><span class="brand-icon"><BookOpen :size="22" /></span
        >AlgoClass</RouterLink
      >

      <nav aria-label="主导航" @click="mobile = false">
        <section class="nav-group" aria-label="课程管理">
          <p>课程管理</p>
          <RouterLink
            to="/teacher"
            exact-active-class="selected"
            :class="{ selected: $route.path === '/teacher' }"
            :aria-current="$route.path === '/teacher' ? 'page' : undefined"
            ><LayoutDashboard :size="19" />课程概览</RouterLink
          ><RouterLink
            to="/teacher/assignments"
            :class="{
              selected: $route.path.startsWith('/teacher/assignments'),
            }"
            :aria-current="
              $route.path.startsWith('/teacher/assignments')
                ? 'page'
                : undefined
            "
            ><ClipboardList :size="19" />作业管理</RouterLink
          ><RouterLink
            to="/teacher/problems"
            :class="{ selected: $route.path.startsWith('/teacher/problems') }"
            :aria-current="
              $route.path.startsWith('/teacher/problems') ? 'page' : undefined
            "
            ><LibraryBig :size="19" />题库管理</RouterLink
          ><RouterLink
            to="/teacher/students"
            :class="{ selected: $route.path.startsWith('/teacher/students') }"
            :aria-current="
              $route.path.startsWith('/teacher/students') ? 'page' : undefined
            "
            ><Users :size="19" />学生名单</RouterLink
          >
        </section>
        <section class="nav-group" aria-label="评分与分析">
          <p>评分与分析</p>
          <RouterLink
            to="/teacher/reviews"
            :class="{ selected: $route.path.startsWith('/teacher/reviews') }"
            :aria-current="
              $route.path.startsWith('/teacher/reviews') ? 'page' : undefined
            "
            ><ClipboardList :size="19" />互评与复核</RouterLink
          ><RouterLink
            to="/teacher/results"
            :class="{ selected: $route.path === '/teacher/results' }"
            :aria-current="
              $route.path === '/teacher/results' ? 'page' : undefined
            "
            ><ClipboardList :size="19" />逐题结果</RouterLink
          ><RouterLink
            to="/teacher/analysis"
            :class="{ selected: $route.path === '/teacher/analysis' }"
            :aria-current="
              $route.path === '/teacher/analysis' ? 'page' : undefined
            "
            ><ChartNoAxesCombined :size="19" />分析中心</RouterLink
          >
        </section>
        <section class="nav-group" aria-label="代码检查">
          <p>代码检查</p>
          <RouterLink
            to="/teacher/similarity"
            :class="{ selected: $route.path.startsWith('/teacher/similarity') }"
            :aria-current="
              $route.path.startsWith('/teacher/similarity') ? 'page' : undefined
            "
            ><Layers :size="19" />相似检测</RouterLink
          ><RouterLink
            to="/teacher/complexity"
            :class="{ selected: $route.path.startsWith('/teacher/complexity') }"
            :aria-current="
              $route.path.startsWith('/teacher/complexity') ? 'page' : undefined
            "
            ><Activity :size="19" />复杂度分析</RouterLink
          >
        </section>
      </nav>
    </aside>
    <div v-if="mobile" class="scrim" @click="mobile = false"></div>
    <div class="main-shell">
      <header class="topbar">
        <button
          class="icon-button mobile-menu"
          :aria-label="mobile ? '关闭导航' : '打开导航'"
          aria-controls="teacher-sidebar"
          :aria-expanded="mobile"
          @click="mobile = !mobile"
        >
          <Menu :size="22" />
        </button>
        <div class="course-select">
          <div>
            <select
              :value="session.courseId"
              :disabled="switchingCourse"
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
          <RouterLink to="/courses" class="button subtle"
            >切换工作区</RouterLink
          >
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
      <main id="main-content" class="page teacher-page" tabindex="-1">
        <div v-if="error" class="alert error">{{ error }}</div>
        <RouterView :key="`${session.courseId}:${$route.path}`" />
      </main>
    </div>
  </div>
</template>
