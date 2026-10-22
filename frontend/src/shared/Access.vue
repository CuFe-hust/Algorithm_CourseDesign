<script setup lang="ts">
import { useRouter } from "vue-router";
import { logout } from "./session";
const router = useRouter();
async function leave() {
  await logout();
  await router.replace("/login");
}
</script>
<template>
  <main class="center-page card">
    <h1>当前账户没有教师课程权限</h1>
    <p class="muted">
      本次交付提供教师工作台。学生端与互评模块由小组成员接入。
    </p>
    <button @click="leave">退出登录</button>
  </main>
</template>
