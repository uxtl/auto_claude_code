<script setup lang="ts">
import { computed } from 'vue'
import type { TaskItem } from '../composables/useTasks'

const props = defineProps<{
  task: TaskItem
}>()

const emit = defineEmits<{
  select: [task: TaskItem]
  retry: [name: string]
  forceRun: [name: string]
}>()

const taskNumber = computed(() => {
  const m = props.task.name.match(/^(\d+)/)
  return m ? `#${m[1]}` : ''
})

const description = computed(() => {
  // Prefer API description field, fallback to slug parsing
  if (props.task.description) return props.task.description
  return props.task.name.replace(/_/g, ' ').replace(/^\d+\s*/, '')
})

const depsLabel = computed(() => {
  if (!props.task.depends || props.task.depends.length === 0) return ''
  return props.task.depends.map(d => `#${String(d).padStart(3, '0')}`).join(', ')
})
</script>

<template>
  <div class="kanban-card" :class="{ 'card-blocked': task.blocked }" @click="emit('select', task)">
    <div class="card-header">
      <span v-if="taskNumber" class="task-num">{{ taskNumber }}</span>
      <span class="card-title">{{ task.name }}</span>
    </div>
    <div class="card-desc">{{ description }}</div>
    <div class="card-footer">
      <div class="card-tags">
        <span v-if="task.worker" class="worker-tag">{{ task.worker }}</span>
        <span v-if="task.blocked" class="blocked-tag">Blocked</span>
        <span v-if="depsLabel" class="deps-tag">after {{ depsLabel }}</span>
      </div>
      <div class="card-actions">
        <button
          v-if="task.blocked"
          class="btn btn-ghost btn-sm"
          title="Force run (ignore dependencies)"
          @click.stop="emit('forceRun', task.name)"
        >Force</button>
        <button
          v-if="task.status === 'failed'"
          class="btn btn-warning btn-sm"
          @click.stop="emit('retry', task.name)"
        >Retry</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kanban-card {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 0.75rem;
  cursor: pointer;
  transition: all var(--transition);
  border: 1px solid transparent;
}
.kanban-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
  border-color: var(--border);
}
.kanban-card.card-blocked {
  opacity: 0.7;
  border-color: var(--border);
  border-style: dashed;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.25rem;
}
.task-num {
  font-size: 0.6875rem;
  font-family: var(--font-mono);
  background: var(--blue-bg);
  color: #3A5A8C;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 700;
  flex-shrink: 0;
}
.card-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-desc {
  font-size: 0.75rem;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 0.5rem;
  line-height: 1.4;
}
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.card-tags {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-wrap: wrap;
}
.card-actions {
  display: flex;
  gap: 0.25rem;
}
.worker-tag {
  font-size: 0.6875rem;
  font-family: var(--font-mono);
  background: var(--blue-bg);
  color: #3A5A8C;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.blocked-tag {
  font-size: 0.625rem;
  background: #FEF3C7;
  color: #92400E;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.deps-tag {
  font-size: 0.625rem;
  font-family: var(--font-mono);
  color: var(--muted);
  padding: 1px 4px;
}
</style>
