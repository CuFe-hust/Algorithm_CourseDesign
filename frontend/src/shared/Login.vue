<script setup lang="ts">
import { ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { BookOpen, ArrowRight } from "@lucide/vue";
import { login, session } from "./session";
import { errorText } from "./api";
const router = useRouter(),
  route = useRoute();
const name = ref(""),
  password = ref(""),
  busy = ref(false),
  error = ref("");
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await login(name.value.trim(), password.value);
    password.value = "";
    const next = String(route.query.next || "");
    await router.replace(
      session.courses.some((c) => c.role === "TEACHER")
        ? next.startsWith("/teacher")
          ? next
          : "/teacher"
        : "/access",
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-page">
    <section class="login-story">
      <div class="brand"><BookOpen :size="25" /> AlgoClass</div>
      <div>
        <span class="eyebrow">ALGORITHM COURSE WORKSPACE</span>
        <h1>让教学准备，<br />有条不紊。</h1>
        <p>
          从一道好题开始，连接课程、学生与反馈。<br />算法设计与分析 ·
          教师工作台
        </p>
      </div>
      <small>课程设计 · 共享课程平台</small>
    </section>
    <section class="login-form">
      <form @submit.prevent="submit">
        <span class="eyebrow">WELCOME BACK</span>
        <h2>登录课程工作台</h2>
        <p class="muted">使用课程平台账户继续</p>
        <div v-if="error" class="alert error" role="alert">{{ error }}</div>
        <label
          >登录名<input
            v-model="name"
            autocomplete="username"
            required
            maxlength="64"
            placeholder="请输入登录名"
            autofocus /></label
        ><label
          >密码<input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            placeholder="请输入密码" /></label
        ><button class="primary full" :disabled="busy">
          {{ busy ? "正在登录…" : "登录工作台" }}<ArrowRight :size="17" />
        </button>
        <p class="hint">尚未激活或忘记密码，请联系课程管理员。</p>
      </form>
    </section>
  </main>
</template>
