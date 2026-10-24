<script setup lang="ts">
const props = defineProps<{
  status: string;
  phase?: string;
  queueReason?: string | null;
}>();
const labels: Record<string, string> = {
  PENDING: "排队中",
  RUNNING: "评测中",
  SUCCEEDED: "评测完成",
  FAILED: "服务故障",
  CANCELLED: "已取消",
  AWAITING_REVIEW: "等待后续处理",
  SUBMITTED: "已提交",
  WITHDRAWN: "已撤回",
};
const tones: Record<string, string> = {
  SUCCEEDED: "green",
  RUNNING: "amber",
  PENDING: "amber",
  FAILED: "red",
  CANCELLED: "gray",
  WITHDRAWN: "gray",
  AWAITING_REVIEW: "gray",
  SUBMITTED: "type",
};
const phaseLabels: Record<string, string> = {
  QUEUED: "排队",
  RETRY_WAIT: "等待重试",
  COMPILING: "编译检查",
  TESTING: "运行测试",
  RECOVERING: "恢复清理",
  FINISHED: "已结束",
};
const reasonLabels: Record<string, string> = {
  RESOURCE_WAIT: "等待资源名额",
  PERSONAL_LIMIT: "本人同时执行已达上限",
  RETRY_BACKOFF: "自动重试退避中",
  SERVICE_PAUSED: "评测服务暂停",
};
</script>
<template>
  <span class="badge" :class="tones[props.status] || 'gray'">
    {{ labels[props.status] || props.status }}
    <template v-if="props.phase && props.status === 'RUNNING'">
      · {{ phaseLabels[props.phase] || props.phase }}
    </template>
  </span>
  <span v-if="props.queueReason" class="badge gray">
    {{ reasonLabels[props.queueReason] || props.queueReason }}
  </span>
</template>
