<script setup lang="ts">
import { ref, watch } from 'vue'
import type { TaskItem, TaskDetail as TaskDetailType } from '../composables/useTasks'
import type { Execution } from '../composables/useExecutions'
import MarkdownView from './MarkdownView.vue'
import ResultView from './ResultView.vue'

const props = defineProps<{
  task: TaskItem | null
  getContent: (name: string) => Promise<TaskDetailType>
  loadExecs: (name: string) => Promise<Execution[]>
}>()

const emit = defineEmits<{
  close: []
  retry: [name: string]
  delete: [name: string]
  update: [name: string, content: string]
  forceRun: [name: string]
}>()

const detail = ref<TaskDetailType | null>(null)
const executions = ref<Execution[]>([])
const editing = ref(false)
const editContent = ref('')
const loading = ref(false)
const expandedExec = ref<number | null>(null)

watch(() => props.task, async (t) => {
  detail.value = null
  executions.value = []
  editing.value = false
  expandedExec.value = null
  if (t) {
    loading.value = true
    try {
      const [d, e] = await Promise.all([
        props.getContent(t.name),
        props.loadExecs(t.name),
      ])
      detail.value = d
      executions.value = e
    } catch { /* ignore */ } finally {
      loading.value = false
    }
  }
}, { immediate: true })

function startEdit() {
  if (detail.value) {
    editContent.value = detail.value.clean_content.trimEnd()
    editing.value = true
  }
}

function saveEdit() {
  if (props.task && editContent.value.trim()) {
    emit('update', props.task.name, editContent.value)
    editing.value = false
  }
}

function formatDuration(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(0)
  return `${m}m ${sec}s`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString()
}
</script>

<template>
  <div class="detail-panel" v-if="task">
    <div class="detail-header">
      <div>
        <h3>{{ task.name }}</h3>
        <span class="badge" :class="'badge-' + task.status">{{ task.status }}</span>
      </div>
      <button class="btn btn-ghost btn-sm" @click="emit('close')">Close</button>
    </div>

    <div v-if="loading" class="detail-loading">Loading...</div>

    <div v-else-if="detail" class="detail-body">
      <!-- Pending: show deps + content + edit -->
      <template v-if="task.status === 'pending'">
        <div v-if="task.depends && task.depends.length" class="detail-section">
          <h4>Dependencies</h4>
          <div class="deps-info">
            <span class="deps-list">
              Depends on:
              <span v-for="(d, i) in task.depends" :key="d">
                <span class="dep-num" :class="{ 'dep-met': !task.unmet_deps?.includes(d), 'dep-unmet': task.unmet_deps?.includes(d) }">
                  #{{ String(d).padStart(3, '0') }}
                </span>{{ i < task.depends.length - 1 ? ', ' : '' }}
              </span>
            </span>
            <span v-if="task.blocked" class="blocked-badge">Blocked</span>
          </div>
          <button
            v-if="task.blocked"
            class="btn btn-warning btn-sm"
            style="margin-top: 0.5rem"
            @click="emit('forceRun', task.name)"
          >Force Run (ignore dependencies)</button>
        </div>
        <div v-if="!editing" class="detail-section">
          <h4>Task Content</h4>
          <MarkdownView :content="detail.clean_content" />
          <div class="detail-actions">
            <button class="btn btn-primary btn-sm" @click="startEdit">Edit</button>
            <button class="btn btn-danger btn-sm" @click="emit('delete', task.name)">Delete</button>
          </div>
        </div>
        <div v-else class="detail-section">
          <h4>Edit Task</h4>
          <textarea v-model="editContent" rows="10" class="edit-textarea"></textarea>
          <div class="detail-actions">
            <button class="btn btn-success btn-sm" @click="saveEdit">Save</button>
            <button class="btn btn-ghost btn-sm" @click="editing = false">Cancel</button>
          </div>
        </div>
      </template>

      <!-- Running: show phase + timer -->
      <template v-else-if="task.status === 'running'">
        <div class="detail-section">
          <h4>Execution</h4>
          <div class="detail-meta">
            <div><strong>Worker:</strong> {{ task.worker }}</div>
          </div>
        </div>
        <div class="detail-section" v-if="detail.clean_content">
          <h4>Task Content</h4>
          <MarkdownView :content="detail.clean_content" />
        </div>
      </template>

      <!-- Done: show ResultView prominently -->
      <template v-else-if="task.status === 'done'">
        <div class="detail-section" v-if="executions.length">
          <h4>Latest Result</h4>
          <ResultView :execution="executions[0]" />
        </div>
        <div class="detail-section">
          <h4>Task Content</h4>
          <MarkdownView :content="detail.clean_content" />
        </div>
      </template>

      <!-- Failed: show errors + ResultView -->
      <template v-else-if="task.status === 'failed'">
        <div class="detail-section" v-if="detail.errors.length">
          <h4>Errors</h4>
          <div class="error-list">
            <div v-for="(e, i) in detail.errors" :key="i" class="error-item">{{ e }}</div>
          </div>
        </div>
        <div class="detail-meta">
          <div><strong>Retries:</strong> {{ detail.retry_count }} / max</div>
        </div>
        <div class="detail-section" v-if="executions.length">
          <h4>Last Execution Details</h4>
          <ResultView :execution="executions[0]" />
        </div>
        <div class="detail-section" v-if="detail.diagnostics.length">
          <h4>Diagnostics</h4>
          <pre class="diag-pre" v-for="(d, i) in detail.diagnostics" :key="i">{{ d }}</pre>
        </div>
        <div class="detail-section">
          <h4>Task Content</h4>
          <MarkdownView :content="detail.clean_content" />
        </div>
        <div class="detail-actions">
          <button class="btn btn-warning btn-sm" @click="emit('retry', task.name)">Retry</button>
          <button class="btn btn-danger btn-sm" @click="emit('delete', task.name)">Delete</button>
        </div>
      </template>

      <!-- Execution History -->
      <div class="detail-section" v-if="executions.length > (task.status === 'done' ? 1 : (task.status === 'failed' ? 1 : 0))">
        <h4>Execution History</h4>
        <div
          v-for="exec in executions.slice(task.status === 'done' || task.status === 'failed' ? 1 : 0)"
          :key="exec.id"
          class="exec-item"
          @click="expandedExec = expandedExec === exec.id ? null : exec.id"
        >
          <div class="exec-summary">
            <span :style="{ color: exec.success ? 'var(--green)' : 'var(--red)' }">
              {{ exec.success ? 'OK' : 'FAIL' }}
            </span>
            <span>{{ exec.worker_id }}</span>
            <span>{{ formatDuration(exec.duration_seconds) }}</span>
            <span>{{ formatTime(exec.created_at) }}</span>
          </div>
          <div v-if="expandedExec === exec.id" class="exec-detail">
            <ResultView :execution="exec" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-panel {
  padding: 1.25rem;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}
.detail-header h3 {
  font-size: 1rem;
  margin-bottom: 0.25rem;
}
.detail-loading {
  color: var(--muted);
  padding: 2rem;
  text-align: center;
}
.detail-section {
  margin-bottom: 1.25rem;
}
.detail-section h4 {
  font-size: 0.8125rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.5rem;
}
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.875rem;
  margin-bottom: 0.75rem;
}
.detail-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.edit-textarea {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 10px 12px;
  font-size: 0.875rem;
  font-family: var(--font-mono);
  resize: vertical;
  min-height: 200px;
  line-height: 1.5;
}
.edit-textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.error-list {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.error-item {
  background: var(--red-bg);
  color: #9B3728;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
  font-family: var(--font-mono);
}
.diag-pre {
  background: #F0EBE4;
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  overflow-x: auto;
  white-space: pre-wrap;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}
.exec-item {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.5rem;
  cursor: pointer;
  transition: background var(--transition);
}
.exec-item:hover {
  background: var(--surface-hover);
}
.exec-summary {
  display: flex;
  gap: 1rem;
  font-size: 0.8125rem;
}
.exec-detail {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border);
}
.deps-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.deps-list {
  font-size: 0.875rem;
  color: var(--text);
}
.dep-num {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 0.8125rem;
}
.dep-met {
  color: var(--green);
}
.dep-unmet {
  color: var(--red);
}
.blocked-badge {
  font-size: 0.6875rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  background: #FEF3C7;
  color: #92400E;
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
