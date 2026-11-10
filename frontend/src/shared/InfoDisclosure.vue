<script setup lang="ts">
import { Info } from "@lucide/vue";

defineProps<{ label: string }>();
</script>

<template>
  <details class="info-disclosure">
    <summary :aria-label="label">
      <Info :size="18" aria-hidden="true" />
      <span>{{ label }}</span>
    </summary>
    <div class="info-disclosure-content"><slot /></div>
  </details>
</template>
