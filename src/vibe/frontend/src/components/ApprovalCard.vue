<script setup lang="ts">
import { computed } from 'vue'
import type { ApprovalItem } from '../composables/useApprovals'

const props = defineProps<{ approval: ApprovalItem }>()
const emit = defineEmits<{
  openApproval: [approval: ApprovalItem]
}>()

const elapsed = computed(() => {
  const ms = Date.now() - new Date(props.approval.created_at).getTime()
  const secs = Math.floor(ms / 1000)
  const mins = Math.floor(secs / 60)
  if (mins > 0) return `${mins}m ${secs % 60}s`
  return `${secs}s`
})
</script>

<template>
  <div class="approval-card-compact" @click="emit('openApproval', approval)">
    <div class="ac-top">
      <span class="badge badge-review">Review</span>
      <strong>{{ approval.task_name }}</strong>
    </div>
    <div class="ac-meta">
      Worker: {{ approval.worker_id }} | Waiting: {{ elapsed }}
    </div>
    <button class="btn btn-primary btn-sm ac-btn">View Plan</button>
  </div>
</template>

<style scoped>
.approval-card-compact {
  background: var(--surface);
  border: 1px solid rgba(123, 94, 167, 0.3);
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  cursor: pointer;
  transition: all var(--transition);
}
.approval-card-compact:hover {
  border-color: var(--purple);
  box-shadow: var(--shadow);
}
.ac-top {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}
.ac-top strong {
  font-size: 0.875rem;
}
.ac-meta {
  font-size: 0.75rem;
  color: var(--muted);
  margin-bottom: 0.5rem;
}
.ac-btn {
  width: 100%;
}
</style>
