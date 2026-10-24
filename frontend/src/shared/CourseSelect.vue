<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  BookOpen,
  ChevronRight,
  GraduationCap,
  LogOut,
  Users,
} from "@lucide/vue";
import { errorText } from "./api";
import {
  currentCourse,
  loadCourses,
  loadSession,
  logout,
  selectCourse,
  session,
  type Course,
} from "./session";
import { startActivityTracking } from "./activity";

const router = useRouter();
const loading = ref(true);
const busy = ref("");
const error = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    await loadSession();
    if (session.mustChangePassword) {
      await router.replace("/account/change-password");
      return;
    }
    await loadCourses();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function choose(course: Course) {
  busy.value = course.id;
  error.value = "";
  selectCourse(course.id);
  startActivityTracking();
  const target =
    course.role === "TEACHER" ? "/teacher" : `/student/courses/${course.id}`;
  await router.replace(target);
  busy.value = "";
}

async function leave() {
  await router.replace("/login");
  if (router.currentRoute.value.path !== "/login") return;
  await logout();
}

onMounted(() => {
  const existing = currentCourse();
  if (existing && session.courses.length) return;
  void load();
});
</script>
<template>
  <main class="center-page card course-picker">
    <div class="page-heading">
      <span class="eyebrow"><BookOpen :size="14" /> SELECT COURSE</span>
      <h1>选择要进入的课程</h1>
      <p class="muted">
        同一个账号在不同课程中可能是教师或学生，进入后按该课程的角色显示功能。
      </p>
    </div>
    <div v-if="error" class="alert error" role="alert">
      {{ error }}
      <button @click="load">重试</button>
    </div>
    <div v-if="loading" class="loading">正在读取课程…</div>
    <div v-else-if="!session.courses.length" class="empty">
      <Users :size="30" />
      <h3>当前账号还没有可访问的课程</h3>
      <p>请联系任课教师完成课程名单导入或账号开通后重试。</p>
      <button class="small" @click="load">重新加载</button>
    </div>
    <ul v-else class="course-list">
      <li v-for="course in session.courses" :key="course.id">
        <button
          class="course-card"
          :disabled="busy === course.id"
          @click="choose(course)"
        >
          <span class="course-icon">
            <GraduationCap v-if="course.role === 'TEACHER'" :size="20" />
            <Users v-else :size="20" />
          </span>
          <span class="course-info">
            <strong>{{ course.name }}</strong>
            <small>{{ course.term }}</small>
          </span>
          <span
            class="badge"
            :class="course.role === 'TEACHER' ? 'type' : 'green'"
          >
            {{ course.role === "TEACHER" ? "任课教师" : "课程学生" }}
          </span>
          <ChevronRight :size="18" />
        </button>
      </li>
    </ul>
    <div class="picker-footer">
      <button class="small" @click="leave">
        <LogOut :size="15" />退出登录
      </button>
    </div>
  </main>
</template>
