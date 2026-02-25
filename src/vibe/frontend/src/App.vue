<script setup lang="ts">
import { ref } from 'vue'
import { useTasks } from './composables/useTasks'
import { useLogs } from './composables/useLogs'
import { useApprovals } from './composables/useApprovals'
import { useWorkers } from './composables/useWorkers'
import { useExecutions } from './composables/useExecutions'
import { useConfig } from './composables/useConfig'
import type { TaskItem } from './composables/useTasks'
import type { ApprovalItem } from './composables/useApprovals'

import StatsBar from './components/StatsBar.vue'
import TaskForm from './components/TaskForm.vue'
import KanbanBoard from './components/KanbanBoard.vue'
import TaskDetail from './components/TaskDetail.vue'
import LogPanel from './components/LogPanel.vue'
import ApprovalModal from './components/ApprovalModal.vue'
import WorkersView from './views/WorkersView.vue'
import HistoryView from './views/HistoryView.vue'
import ConfigView from './views/ConfigView.vue'

const { tasks, counts, addTask, deleteTask, retryTask, forceRunTask, getContent, updateContent, batchAction } = useTasks()
const { logs, connected, filterWorker, filterText, clear: clearLogs, download: downloadLogs } = useLogs()
const { approvals, approve, reject } = useApprovals()
const { workers } = useWorkers()
const { executions, loading: execLoading, loadRecent, loadByTask } = useExecutions()
const { config } = useConfig()

const selectedTask = ref<TaskItem | null>(null)
const activeApproval = ref<ApprovalItem | null>(null)
const openDrawer = ref<'workers' | 'history' | 'config' | null>(null)

function selectTask(task: TaskItem) {
  selectedTask.value = task
}

function closeDetail() {
  selectedTask.value = null
}

async function handleRetry(name: string) {
  await retryTask(name)
  if (selectedTask.value?.name === name) {
    selectedTask.value = null
  }
}

async function handleDelete(name: string) {
  if (!confirm(`Delete task: ${name}?`)) return
  await deleteTask(name)
  if (selectedTask.value?.name === name) {
    selectedTask.value = null
  }
}

async function handleUpdate(name: string, content: string) {
  await updateContent(name, content)
}

function openApprovalModal(approval: ApprovalItem) {
  activeApproval.value = approval
}

async function handleApprove(id: string, feedback: string, selections: Record<string, string>) {
  await approve(id, feedback, selections)
  activeApproval.value = null
}

async function handleReject(id: string) {
  await reject(id)
  activeApproval.value = null
}
</script>

<template>
  <div class="app-layout">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <h1><span class="brand">Claude Code</span> Task Manager</h1>
        <span class="conn-indicator" :class="{ online: connected }" :title="connected ? 'Connected' : 'Disconnected'"></span>
      </div>
      <div class="header-right">
        <div class="header-badges">
          <span v-if="config" class="header-badge">workers: {{ config.max_workers }}</span>
          <span v-if="config" class="header-badge" :class="{ active: config.plan_mode }">plan {{ config.plan_mode ? 'ON' : 'off' }}</span>
          <span v-if="config" class="header-badge" :class="{ active: config.use_docker }">docker {{ config.use_docker ? 'ON' : 'off' }}</span>
        </div>
        <div class="header-nav">
          <button class="nav-icon-btn" :class="{ active: openDrawer === 'workers' }" @click="openDrawer = openDrawer === 'workers' ? null : 'workers'" title="Workers">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="7" r="4"/><path d="M5.5 21a6.5 6.5 0 0 1 13 0"/></svg>
          </button>
          <button class="nav-icon-btn" :class="{ active: openDrawer === 'history' }" @click="openDrawer = openDrawer === 'history' ? null : 'history'; if (openDrawer === 'history') loadRecent()" title="History">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          </button>
          <button class="nav-icon-btn" :class="{ active: openDrawer === 'config' }" @click="openDrawer = openDrawer === 'config' ? null : 'config'" title="Config">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </div>
      </div>
    </header>

    <!-- TopBar: TaskForm + Stats -->
    <TaskForm @submit="(desc, deps) => addTask(desc, deps)" @batch="batchAction" />
    <StatsBar
      :pending="counts.pending"
      :running="counts.running"
      :done="counts.done"
      :failed="counts.failed"
      :awaiting="approvals.length"
      :blocked="counts.blocked"
    />

    <!-- Main Area: Kanban -->
    <div class="main-area">
      <KanbanBoard
        :tasks="tasks"
        :approvals="approvals"
        @select="selectTask"
        @retry="handleRetry"
        @force-run="forceRunTask"
        @open-approval="openApprovalModal"
      />

      <!-- Detail slide panel -->
      <Transition name="slide-panel">
        <div v-if="selectedTask" class="slide-panel">
          <TaskDetail
            :task="selectedTask"
            :get-content="getContent"
            :load-execs="loadByTask"
            @close="closeDetail"
            @retry="handleRetry"
            @delete="handleDelete"
            @update="handleUpdate"
            @force-run="forceRunTask"
          />
        </div>
      </Transition>
      <div v-if="selectedTask" class="overlay" @click="closeDetail"></div>
    </div>

    <!-- Log panel -->
    <LogPanel
      :logs="logs"
      :connected="connected"
      :filter-worker="filterWorker"
      :filter-text="filterText"
      @update:filter-worker="filterWorker = $event"
      @update:filter-text="filterText = $event"
      @clear="clearLogs"
      @download="downloadLogs"
    />

    <!-- Approval Modal -->
    <ApprovalModal
      :approval="activeApproval"
      @approve="handleApprove"
      @reject="handleReject"
      @close="activeApproval = null"
    />

    <!-- Drawers -->
    <Transition name="drawer">
      <div v-if="openDrawer" class="drawer">
        <div class="drawer-header">
          <h3>{{ openDrawer === 'workers' ? 'Workers' : openDrawer === 'history' ? 'Execution History' : 'Configuration' }}</h3>
          <button class="btn btn-ghost btn-sm" @click="openDrawer = null">Close</button>
        </div>
        <WorkersView v-if="openDrawer === 'workers'" :workers="workers" />
        <HistoryView
          v-else-if="openDrawer === 'history'"
          :executions="executions"
          :loading="execLoading"
          @load="loadRecent()"
        />
        <ConfigView v-else-if="openDrawer === 'config'" :config="config" />
      </div>
    </Transition>
    <div v-if="openDrawer" class="drawer-overlay" @click="openDrawer = null"></div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.app-header h1 {
  font-size: 1.125rem;
  font-weight: 600;
}
.brand {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--accent);
  font-weight: 600;
}
.conn-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--red);
  transition: background 0.3s;
}
.conn-indicator.online {
  background: var(--green);
  box-shadow: 0 0 6px var(--green);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.header-badges {
  display: flex;
  gap: 0.5rem;
}
.header-badge {
  font-size: 0.6875rem;
  font-family: var(--font-mono);
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg);
  color: var(--muted);
  border: 1px solid var(--border);
}
.header-badge.active {
  color: #3A6347;
  border-color: var(--green);
  background: var(--green-bg);
}
.header-nav {
  display: flex;
  gap: 0.25rem;
}
.nav-icon-btn {
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--muted);
  cursor: pointer;
  padding: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
}
.nav-icon-btn:hover {
  color: var(--text);
  background: var(--surface-hover);
}
.nav-icon-btn.active {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(184, 92, 56, 0.06);
}

.main-area {
  flex: 1;
  overflow: hidden;
  position: relative;
}
</style>
