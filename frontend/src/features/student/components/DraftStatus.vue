<script setup lang="ts">
import { computed } from "vue";
import type { DraftRecord } from "../draft-store";
import { formatTime } from "../format";
const props = defineProps<{
  status: "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";
  message?: string;
  lastSavedAt?: number | null;
  degraded?: boolean;
  conflict?: DraftRecord | null;
}>();
const emit = defineEmits<{ accept: []; dismiss: [] }>();
const label = computed(
  () =>
    ({
      idle: "没有未保存的修改",
      dirty: "有未保存的修改",
      saving: "正在保存草稿…",
      saved: props.lastSavedAt
        ? `草稿已保存于本机 ${formatTime(props.lastSavedAt)}`
        : "草稿已保存于本机",
      error: "草稿保存失败",
      conflict: "检测到多标签页编辑冲突",
    })[props.status],
);
</script>
<template>
  <div class="draft-status" :class="status">
    <span>{{ label }}</span>
    <span v-if="degraded" class="badge amber"
      >本机存储不可用，草稿不会跨刷新保留</span
    >
    <p v-if="message" class="muted">{{ message }}</p>
    <div v-if="status === 'conflict'" class="draft-conflict">
      <p>
        另一标签页保存了更新的草稿（修订号
        {{ conflict?.revision }}）。请选择保留哪一份。
      </p>
      <button class="small" @click="emit('accept')">
        使用另一标签页的内容
      </button>
      <button class="small" @click="emit('dismiss')">保留当前编辑内容</button>
    </div>
  </div>
</template>
