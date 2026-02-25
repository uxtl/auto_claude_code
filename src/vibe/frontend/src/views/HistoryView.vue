<script setup lang="ts">
import { onMounted } from 'vue'
import type { Execution } from '../composables/useExecutions'
import ExecutionList from '../components/ExecutionList.vue'

const props = defineProps<{
  executions: Execution[]
  loading: boolean
}>()

const emit = defineEmits<{ load: [] }>()

onMounted(() => emit('load'))
</script>

<template>
  <div class="history-view">
    <div class="history-header">
      <h3>Execution History</h3>
      <button class="btn btn-ghost btn-sm" @click="emit('load')">Refresh</button>
    </div>
    <div v-if="loading" class="empty">Loading...</div>
    <ExecutionList v-else :executions="executions" />
  </div>
</template>

<style scoped>
.history-view {
  height: 100%;
  overflow-y: auto;
}
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
}
.history-header h3 {
  font-size: 0.9375rem;
}
</style>
