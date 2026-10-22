<script setup lang="ts">
import { computed } from "vue";
import { renderCode } from "./markdown";
import "highlight.js/styles/github.css";
const props = defineProps<{ source: string; language: string }>();
const html = computed(() => renderCode(props.source, props.language));
</script>
<template>
  <div class="markdown">
    <pre><code v-html="html"></code></pre>
  </div>
</template>
