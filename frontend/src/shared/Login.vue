<script setup lang="ts">
import { ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { BookOpen, ArrowRight, Eye, EyeOff } from "@lucide/vue";
import { login, session } from "./session";
import { errorText } from "./api";
import { startActivityTracking } from "./activity";
import { safeInternalPath } from "./navigation";
const router = useRouter(),
  route = useRoute();
const name = ref(""),
  password = ref(""),
  busy = ref(false),
  visiblePassword = ref(false),
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
  <main class="access-page">
    <section class="access-context" aria-label="平台介绍">
      <div class="brand">
        <BookOpen :size="24" aria-hidden="true" /> AlgoClass
      </div>
      <div class="access-context-title">
        <h1>算法设计与分析</h1>
        <p>课程作业与评阅</p>
      </div>
    </section>
    <section class="access-form" aria-labelledby="login-title">
      <form @submit.prevent="submit">
        <h2 id="login-title">登录</h2>
        <div v-if="error" class="alert error" role="alert">{{ error }}</div>
        <label for="account-name">登录名</label>
        <input
          id="account-name"
          v-model="name"
          autocomplete="username"
          required
          maxlength="64"
          placeholder="请输入登录名"
          autofocus
        />
        <label for="account-password">密码</label>
        <div class="password-field">
          <input
            id="account-password"
            v-model="password"
            :type="visiblePassword ? 'text' : 'password'"
            autocomplete="current-password"
            required
            placeholder="请输入密码"
          />
          <button
            type="button"
            class="password-toggle"
            :aria-label="visiblePassword ? '隐藏密码' : '显示密码'"
            @click="visiblePassword = !visiblePassword"
          >
            <EyeOff v-if="visiblePassword" :size="20" aria-hidden="true" />
            <Eye v-else :size="20" aria-hidden="true" />
          </button>
        </div>
        <button class="primary full" :disabled="busy" :aria-busy="busy">
          {{ busy ? "正在登录…" : "登录"
          }}<ArrowRight :size="18" aria-hidden="true" />
        </button>
        <p class="access-help">账号未开通或忘记密码？请联系任课教师。</p>
      </form>
    </section>
  </main>
</template>
