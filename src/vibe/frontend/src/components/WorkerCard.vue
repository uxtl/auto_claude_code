<script setup lang="ts">
import { computed } from 'vue'
import type { WorkerStatus } from '../composables/useWorkers'

const props = defineProps<{ worker: WorkerStatus }>()

const phases = ['idle', 'claimed', 'planning', 'awaiting_approval', 'executing']

const phaseIndex = computed(() => {
  const idx = phases.indexOf(props.worker.phase)
  return idx >= 0 ? idx : 0
})

const elapsed = computed(() => {
  if (!props.worker.started_at || props.worker.phase === 'idle') return ''
  const secs = Math.floor(Date.now() / 1000 - props.worker.started_at)
  const mins = Math.floor(secs / 60)
  if (mins > 0) return `${mins}m ${secs % 60}s`
  return `${secs}s`
})

const phaseColor = computed(() => {
  switch (props.worker.phase) {
    case 'idle': return 'var(--muted)'
    case 'claimed': return 'var(--yellow)'
    case 'planning': return 'var(--blue)'
    case 'awaiting_approval': return 'var(--purple)'
    case 'executing': return 'var(--green)'
    default: return 'var(--muted)'
  }
})
</script>

<template>
  <div class="worker-card" :class="{ active: worker.phase !== 'idle' }">
    <div class="worker-header">
      <strong>{{ worker.worker_id }}</strong>
      <span class="worker-phase" :style="{ color: phaseColor }">{{ worker.phase }}</span>
    </div>
    <div v-if="worker.task" class="worker-task">{{ worker.task }}</div>
    <div v-else class="worker-idle">No task</div>
    <div class="progress-bar">
      <div
        v-for="(p, i) in phases.slice(1)"
        :key="p"
        class="progress-segment"
        :class="{ filled: i < phaseIndex }"
      ></div>
    </div>
    <div v-if="elapsed" class="worker-elapsed">{{ elapsed }}</div>
  </div>
</template>

<style scoped>
.worker-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  min-width: 220px;
  box-shadow: var(--shadow);
}
.worker-card.active {
  border-color: var(--accent);
}
.worker-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.worker-phase {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}
.worker-task {
  font-size: 0.8125rem;
  color: var(--text);
  margin-bottom: 0.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.worker-idle {
  font-size: 0.8125rem;
  color: var(--muted);
  margin-bottom: 0.5rem;
}
.progress-bar {
  display: flex;
  gap: 3px;
  margin-bottom: 0.5rem;
}
.progress-segment {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--border);
  transition: background 0.3s;
}
.progress-segment.filled {
  background: var(--accent);
}
.worker-elapsed {
  font-size: 0.75rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
</style>
