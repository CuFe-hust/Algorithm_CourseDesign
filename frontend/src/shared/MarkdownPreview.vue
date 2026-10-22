<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "./markdown";
import "katex/dist/katex.min.css";
import "highlight.js/styles/github.css";
const props = defineProps<{ source: string | null | undefined }>();
const html = computed(() => renderMarkdown(props.source || ""));
</script>
<template>
  <div v-if="source" class="markdown" v-html="html"></div>
  <p v-else class="muted">暂无内容</p>
</template>
