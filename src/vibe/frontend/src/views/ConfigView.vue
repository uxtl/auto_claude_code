<script setup lang="ts">
import type { VibeConfig } from '../composables/useConfig'
import ConfigPanel from '../components/ConfigPanel.vue'

defineProps<{ config: VibeConfig | null }>()
</script>

<template>
  <div class="config-view">
    <ConfigPanel :config="config" />
  </div>
</template>

<style scoped>
.config-view {
  height: 100%;
  overflow-y: auto;
}
</style>
