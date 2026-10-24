<script setup lang="ts">
import { useRouter } from "vue-router";
import { ShieldAlert } from "@lucide/vue";
import { logout } from "./session";
const router = useRouter();
async function back() {
  await router.replace("/courses");
}
async function leave() {
  await logout();
  await router.replace("/login");
}
</script>
<template>
  <main class="center-page card">
    <ShieldAlert :size="30" />
    <h1>无法访问该页面</h1>
    <p class="muted">
      当前账号在这门课程中没有对应角色，或该课程已不再对你开放。请重新选择课程；如果是名单问题，请联系任课教师。
    </p>
    <div class="picker-footer">
      <button class="primary" @click="back">重新选择课程</button>
      <button class="small" @click="leave">退出登录</button>
    </div>
  </main>
</template>
