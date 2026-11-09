<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import {
  BookOpen,
  ChartNoAxesCombined,
  ClipboardList,
  History,
  LogOut,
  Menu,
  RefreshCw,
} from "@lucide/vue";
import { errorText } from "../../shared/api";
import { currentCourse, logout, session } from "../../shared/session";
import { stopActivityTracking } from "../../shared/activity";
const router = useRouter();
const mobile = ref(false);
const error = ref("");
const course = computed(() => currentCourse());
async function leave() {
  stopActivityTracking();
  await router.push("/login");
  if (router.currentRoute.value.path !== "/login") return;
  try {
    await logout();
  } catch (e) {
    error.value = errorText(e);
  }
}
async function switchCourse() {
  await router.push("/courses");
}
</script>
<template>
  <div class="workspace">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <aside id="student-sidebar" class="sidebar" :class="{ open: mobile }">
      <RouterLink :to="`/student/courses/${session.courseId}`" class="brand"
        ><span class="brand-icon"><BookOpen :size="22" /></span
        >AlgoClass</RouterLink
      >
      <div class="workspace-label">学生课程 <span>学生端</span></div>
      <nav aria-label="学生导航" @click="mobile = false">
        <RouterLink
          :to="`/student/courses/${session.courseId}`"
          :class="{
            selected: $route.path === `/student/courses/${session.courseId}`,
          }"
          :aria-current="
            $route.path === `/student/courses/${session.courseId}`
              ? 'page'
              : undefined
          "
          ><ClipboardList :size="19" />作业与作答</RouterLink
        >
        <RouterLink
          :to="`/student/courses/${session.courseId}/ability`"
          :class="{ selected: $route.path.endsWith('/ability') }"
          :aria-current="$route.path.endsWith('/ability') ? 'page' : undefined"
          ><ChartNoAxesCombined :size="19" />个人章节表现</RouterLink
        >
        <RouterLink
          :to="`/student/courses/${session.courseId}/submissions`"
          :class="{ selected: $route.path.includes('/submissions') }"
          :aria-current="
            $route.path.includes('/submissions') ? 'page' : undefined
          "
          ><History :size="19" />本人提交</RouterLink
        >
        <RouterLink
          :to="`/student/courses/${$route.params.courseId}/reviews`"
          :class="{ selected: $route.path.includes('/reviews') }"
          :aria-current="$route.path.includes('/reviews') ? 'page' : undefined"
          ><ClipboardList :size="19" />我的互评</RouterLink
        >
        <RouterLink
          :to="`/student/courses/${$route.params.courseId}/learning`"
          :class="{ selected: $route.path.includes('/learning') }"
          :aria-current="$route.path.includes('/learning') ? 'page' : undefined"
          ><ChartNoAxesCombined :size="19" />学习报告</RouterLink
        >
      </nav>
      <button class="sidebar-switch" @click="switchCourse">
        <RefreshCw :size="16" />切换课程
      </button>
      <div class="sidebar-foot">
        <strong>{{ course?.name || "当前课程" }}</strong>
        <p>{{ course?.term }} · 草稿仅保存在本机浏览器</p>
      </div>
    </aside>
    <div v-if="mobile" class="scrim" @click="mobile = false"></div>
    <div class="main-shell">
      <header class="topbar">
        <button
          class="icon-button mobile-menu"
          aria-label="展开导航"
          aria-controls="student-sidebar"
          :aria-expanded="mobile"
          @click="mobile = !mobile"
        >
          <Menu :size="22" />
        </button>
        <div class="course-select">
          <span class="small-label">当前课程</span>
          <div>
            <strong>{{ course?.name || "未选择课程" }}</strong>
          </div>
        </div>
        <div class="account">
          <span class="avatar">{{
            session.user?.full_name?.slice(-2) || "学生"
          }}</span>
          <span
            ><strong>{{ session.user?.full_name }}</strong
            ><small>课程学生</small></span
          >
          <button
            class="icon-button"
            aria-label="退出登录"
            title="退出登录"
            @click="leave"
          >
            <LogOut :size="18" />
          </button>
        </div>
      </header>
      <main id="main-content" class="page student-page" tabindex="-1">
        <div v-if="error" class="alert error">{{ error }}</div>
        <RouterView :key="$route.path" />
      </main>
      <footer class="page-footer">
        AlgoClass · {{ course?.term }}<span>学生作答与评测</span>
      </footer>
    </div>
  </div>
</template>
