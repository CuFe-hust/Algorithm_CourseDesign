<script setup lang="ts">
import { ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { BookOpen, ArrowRight } from "@lucide/vue";
import { login, session } from "./session";
import { errorText } from "./api";
import { startActivityTracking } from "./activity";
import { safeInternalPath } from "./navigation";
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
    const result = await login(name.value.trim(), password.value);
    password.value = "";
    startActivityTracking();
    const next = safeInternalPath(String(route.query.next || ""));
    if (result.must_change_password) {
      await router.replace({
        path: "/account/change-password",
        query: next ? { next } : {},
      });
      return;
    }
    await router.replace({ path: "/courses", query: next ? { next } : {} });
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
        <h1>从一道题开始，<br />看见思考的过程。</h1>
        <p>
          算法设计与分析 · 课程平台<br />同一入口登录，按所选课程进入对应工作区。
        </p>
      </div>
      <small>课程设计 · 共享课程平台</small>
    </section>
    <section class="login-form">
      <form @submit.prevent="submit">
        <span class="eyebrow">WELCOME BACK</span>
        <h2>登录课程平台</h2>
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
          {{ busy ? "正在登录…" : "登录" }}<ArrowRight :size="17" />
        </button>
        <p class="hint">
          首次登录会先要求修改初始密码；账号开通与密码重置请联系任课教师。
        </p>
      </form>
    </section>
  </main>
</template>
