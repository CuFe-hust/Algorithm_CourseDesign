<script setup lang="ts">
defineProps<{ total: number; offset: number; limit: number }>();
defineEmits<{ change: [offset: number] }>();
</script>
<template>
  <div class="pagination">
    <span
      >共 {{ total }} 条 · 当前 {{ total ? offset + 1 : 0 }}–{{
        Math.min(offset + limit, total)
      }}
      条</span
    >
    <div>
      <button
        :disabled="offset === 0"
        @click="$emit('change', Math.max(0, offset - limit))"
      >
        上一页</button
      ><span
        >{{ Math.floor(offset / limit) + 1 }} /
        {{ Math.max(1, Math.ceil(total / limit)) }}</span
      ><button
        :disabled="offset + limit >= total"
        @click="$emit('change', offset + limit)"
      >
        下一页
      </button>
    </div>
  </div>
</template>
