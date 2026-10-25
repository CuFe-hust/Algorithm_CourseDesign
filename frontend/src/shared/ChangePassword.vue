<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { BookOpen, KeyRound } from "@lucide/vue";
import { errorText, validationMessages } from "./api";
import { changePassword, session } from "./session";
import { startActivityTracking } from "./activity";
import { safeInternalPath } from "./navigation";
const router = useRouter();
const route = useRoute();
const current = ref(""),
  next = ref(""),
  confirm = ref(""),
  busy = ref(false),
  error = ref("");
const forced = () => session.mustChangePassword;
async function submit() {
  error.value = "";
  if (next.value !== confirm.value) {
    error.value = "两次输入的新密码不一致。";
    return;
  }
  busy.value = true;
  try {
    await changePassword(current.value, next.value);
    current.value = "";
    next.value = "";
    confirm.value = "";
    startActivityTracking();
    const target = safeInternalPath(String(route.query.next || ""));
    await router.replace({
      path: "/courses",
      query: target ? { next: target } : {},
    });
  } catch (e) {
    const messages = validationMessages((e as { details?: unknown }).details);
    error.value = messages.length ? messages.join("；") : errorText(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="center-page card">
    <div class="page-heading">
      <span class="eyebrow"><KeyRound :size="14" /> ACCOUNT</span>
      <h1>{{ forced() ? "设置你的新密码" : "修改密码" }}</h1>
      <p class="muted">
        {{
          forced()
            ? "初始密码仅用于首次登录。修改后旧会话立即失效，需要重新进入课程。"
            : "修改成功后当前浏览器的登录凭据会更换，其他设备上的会话失效。"
        }}
      </p>
    </div>
    <div v-if="error" class="alert error" role="alert">{{ error }}</div>
    <form class="form-body" @submit.prevent="submit">
      <label
        >当前密码<input
          v-model="current"
          type="password"
          autocomplete="current-password"
          required
          maxlength="128"
      /></label>
      <label
        >新密码<input
          v-model="next"
          type="password"
          autocomplete="new-password"
          required
          minlength="8"
          maxlength="128"
          placeholder="8～128 个字符"
      /></label>
      <label
        >确认新密码<input
          v-model="confirm"
          type="password"
          autocomplete="new-password"
          required
          maxlength="128"
      /></label>
      <button class="primary" :disabled="busy">
        {{ busy ? "正在提交…" : "保存新密码" }}
      </button>
      <p class="hint">
        若响应丢失，新密码已经生效但本页没有新凭据，可用新密码重新登录，不要重复提交。
      </p>
    </form>
    <p class="brand-mark"><BookOpen :size="16" /> AlgoClass</p>
  </main>
</template>
