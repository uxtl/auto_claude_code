<script setup lang="ts">
import { computed } from 'vue'
import type { TaskItem } from '../composables/useTasks'
import type { ApprovalItem } from '../composables/useApprovals'
import KanbanCard from './KanbanCard.vue'

const props = defineProps<{
  tasks: TaskItem[]
  approvals: ApprovalItem[]
}>()

const emit = defineEmits<{
  select: [task: TaskItem]
  retry: [name: string]
  forceRun: [name: string]
  openApproval: [approval: ApprovalItem]
}>()

const columns = computed(() => {
  const pending = props.tasks.filter(t => t.status === 'pending')
  const running = props.tasks.filter(t => t.status === 'running')
  const done = props.tasks.filter(t => t.status === 'done')
  const failed = props.tasks.filter(t => t.status === 'failed')
  return { pending, running, done, failed }
})

function formatElapsed(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  if (mins > 0) return `${mins}m ${secs % 60}s`
  return `${secs}s`
}
</script>

<template>
  <div class="kanban-board">
    <!-- Pending -->
    <div class="kanban-column">
      <div class="column-header">
        <span class="column-dot" style="background: var(--yellow)"></span>
        <span class="column-name">Pending</span>
        <span class="column-count">{{ columns.pending.length }}</span>
      </div>
      <div class="column-body">
        <KanbanCard
          v-for="t in columns.pending"
          :key="t.name"
          :task="t"
          @select="emit('select', $event)"
          @retry="emit('retry', $event)"
          @force-run="emit('forceRun', $event)"
        />
        <div v-if="!columns.pending.length" class="column-empty">No tasks</div>
      </div>
    </div>

    <!-- Running -->
    <div class="kanban-column">
      <div class="column-header">
        <span class="column-dot" style="background: var(--blue)"></span>
        <span class="column-name">Running</span>
        <span class="column-count">{{ columns.running.length }}</span>
      </div>
      <div class="column-body">
        <KanbanCard
          v-for="t in columns.running"
          :key="t.name"
          :task="t"
          @select="emit('select', $event)"
          @retry="emit('retry', $event)"
          @force-run="emit('forceRun', $event)"
        />
        <div v-if="!columns.running.length" class="column-empty">Idle</div>
      </div>
    </div>

    <!-- Review / Approvals -->
    <div class="kanban-column">
      <div class="column-header">
        <span class="column-dot" style="background: var(--purple)"></span>
        <span class="column-name">Review</span>
        <span class="column-count">{{ approvals.length }}</span>
      </div>
      <div class="column-body">
        <div
          v-for="a in approvals"
          :key="a.approval_id"
          class="review-card"
          @click="emit('openApproval', a)"
        >
          <div class="review-title">{{ a.task_name }}</div>
          <div class="review-meta">
            <span class="worker-tag">{{ a.worker_id }}</span>
            <span class="review-elapsed">{{ formatElapsed(a.created_at) }}</span>
          </div>
          <button class="btn btn-primary btn-sm review-btn">View Plan</button>
        </div>
        <div v-if="!approvals.length" class="column-empty">No reviews</div>
      </div>
    </div>

    <!-- Done -->
    <div class="kanban-column">
      <div class="column-header">
        <span class="column-dot" style="background: var(--green)"></span>
        <span class="column-name">Done</span>
        <span class="column-count">{{ columns.done.length }}</span>
      </div>
      <div class="column-body">
        <KanbanCard
          v-for="t in columns.done"
          :key="t.name"
          :task="t"
          @select="emit('select', $event)"
          @retry="emit('retry', $event)"
          @force-run="emit('forceRun', $event)"
        />
        <div v-if="!columns.done.length" class="column-empty">No completed tasks</div>
      </div>
    </div>

    <!-- Failed -->
    <div class="kanban-column">
      <div class="column-header">
        <span class="column-dot" style="background: var(--red)"></span>
        <span class="column-name">Failed</span>
        <span class="column-count">{{ columns.failed.length }}</span>
      </div>
      <div class="column-body">
        <KanbanCard
          v-for="t in columns.failed"
          :key="t.name"
          :task="t"
          @select="emit('select', $event)"
          @retry="emit('retry', $event)"
          @force-run="emit('forceRun', $event)"
        />
        <div v-if="!columns.failed.length" class="column-empty">No failures</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kanban-board {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  height: 100%;
  overflow-x: auto;
}
.kanban-column {
  min-width: 220px;
  max-width: 320px;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-radius: var(--radius);
}
.column-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  flex-shrink: 0;
}
.column-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.column-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text);
}
.column-count {
  font-size: 0.6875rem;
  font-weight: 700;
  background: var(--surface-hover);
  color: var(--muted);
  padding: 1px 7px;
  border-radius: 10px;
  margin-left: auto;
}
.column-body {
  flex: 1;
  overflow-y: auto;
  padding: 0 0.75rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.column-empty {
  color: var(--muted);
  font-size: 0.75rem;
  text-align: center;
  padding: 1rem 0;
  font-style: italic;
}

/* Review card */
.review-card {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 0.75rem;
  cursor: pointer;
  transition: all var(--transition);
  border: 1px solid var(--purple-bg);
}
.review-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
  border-color: var(--purple);
}
.review-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 0.375rem;
}
.review-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
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
.review-elapsed {
  font-size: 0.6875rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.review-btn {
  width: 100%;
}
</style>
