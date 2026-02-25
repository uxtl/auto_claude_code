<script setup lang="ts">
import type { VibeConfig } from '../composables/useConfig'

defineProps<{ config: VibeConfig | null }>()

const groups = [
  {
    label: 'Core',
    keys: ['workspace', 'max_workers', 'timeout', 'max_retries', 'poll_interval'] as const,
  },
  {
    label: 'Modes',
    keys: ['plan_mode', 'plan_auto_approve', 'use_worktree', 'verbose'] as const,
  },
  {
    label: 'Docker',
    keys: ['use_docker', 'docker_image', 'docker_extra_args'] as const,
  },
  {
    label: 'Paths',
    keys: ['task_dir', 'done_dir', 'fail_dir', 'log_level', 'log_file'] as const,
  },
]

function formatValue(val: any): string {
  if (typeof val === 'boolean') return val ? 'Yes' : 'No'
  if (val === '' || val === null || val === undefined) return '-'
  return String(val)
}
</script>

<template>
  <div class="config-panel" v-if="config">
    <div v-for="group in groups" :key="group.label" class="config-group">
      <h4>{{ group.label }}</h4>
      <div class="config-grid">
        <template v-for="key in group.keys" :key="key">
          <div class="config-key">{{ key }}</div>
          <div class="config-val" :class="{ bool: typeof config[key] === 'boolean', active: config[key] === true }">
            {{ formatValue(config[key]) }}
          </div>
        </template>
      </div>
    </div>
  </div>
  <div v-else class="empty">Loading configuration...</div>
</template>

<style scoped>
.config-panel {
  padding: 1rem;
}
.config-group {
  margin-bottom: 1.5rem;
}
.config-group h4 {
  font-size: 0.8125rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.5rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--border);
}
.config-grid {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 0.25rem 1rem;
  font-size: 0.875rem;
}
.config-key {
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
}
.config-val {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  word-break: break-all;
}
.config-val.bool {
  font-weight: 600;
}
.config-val.active {
  color: var(--green);
}
.config-val.bool:not(.active) {
  color: var(--muted);
}
</style>
