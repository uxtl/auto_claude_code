<script setup lang="ts">
import { ref } from 'vue'
import type { Execution } from '../composables/useExecutions'
import ResultView from './ResultView.vue'

defineProps<{ executions: Execution[] }>()

const expandedId = ref<number | null>(null)

function toggle(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function formatDuration(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  return `${m}m ${(s % 60).toFixed(0)}s`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString()
}
</script>

<template>
  <div class="exec-list">
    <div v-if="!executions.length" class="empty">No execution history</div>
    <div
      v-for="exec in executions"
      :key="exec.id"
      class="exec-row"
      @click="toggle(exec.id)"
    >
      <div class="exec-header">
        <span class="exec-status" :style="{ color: exec.success ? 'var(--green)' : 'var(--red)' }">
          {{ exec.success ? 'OK' : 'FAIL' }}
        </span>
        <span class="exec-name">{{ exec.task_name }}</span>
        <span class="exec-meta">{{ exec.worker_id }}</span>
        <span class="exec-meta">{{ formatDuration(exec.duration_seconds) }}</span>
        <span class="exec-meta">{{ exec.files_changed.length }} files</span>
        <span class="exec-meta">{{ exec.tool_calls_count }} tools</span>
        <span class="exec-meta exec-time">{{ formatTime(exec.created_at) }}</span>
      </div>

      <div v-if="expandedId === exec.id" class="exec-detail" @click.stop>
        <ResultView :execution="exec" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.exec-list {
  padding: 0.5rem;
}
.exec-row {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: 0.5rem;
  padding: 0.625rem 0.75rem;
  cursor: pointer;
  transition: background var(--transition);
  background: var(--surface);
}
.exec-row:hover {
  background: var(--surface-hover);
}
.exec-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.8125rem;
  flex-wrap: wrap;
}
.exec-status {
  font-weight: 700;
  font-size: 0.75rem;
  min-width: 32px;
}
.exec-name {
  font-weight: 500;
  flex: 1;
  min-width: 100px;
}
.exec-meta {
  color: var(--muted);
  font-size: 0.75rem;
  white-space: nowrap;
}
.exec-time {
  font-variant-numeric: tabular-nums;
}
.exec-detail {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}
</style>
