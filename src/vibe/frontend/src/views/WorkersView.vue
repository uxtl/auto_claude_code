<script setup lang="ts">
import type { WorkerStatus } from '../composables/useWorkers'
import WorkerCard from '../components/WorkerCard.vue'

defineProps<{ workers: Record<string, WorkerStatus> }>()
</script>

<template>
  <div class="workers-view">
    <div v-if="!Object.keys(workers).length" class="empty">
      No active workers. Workers appear when the task loop is running.
    </div>
    <div class="workers-grid" v-else>
      <WorkerCard
        v-for="(w, id) in workers"
        :key="id"
        :worker="w"
      />
    </div>
  </div>
</template>

<style scoped>
.workers-view {
  padding: 1rem;
  height: 100%;
  overflow-y: auto;
}
.workers-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
</style>
