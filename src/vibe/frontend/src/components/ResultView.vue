<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Execution } from '../composables/useExecutions'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{
  execution: Execution
}>()

const showRawOutput = ref(false)
const showToolTimeline = ref(false)

function formatDuration(s: number): string {
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(0)
  return `${m}m ${sec}s`
}

// Build paired tool timeline from tool_calls_summary + tool_results_summary
const toolTimeline = computed(() => {
  const calls = props.execution.tool_calls_summary || []
  const results = props.execution.tool_results_summary || []
  const resultMap = new Map<string, { is_error: boolean; snippet: string }>()
  for (const r of results) {
    if (r.tool_use_id) {
      resultMap.set(r.tool_use_id, { is_error: r.is_error, snippet: r.snippet })
    }
  }

  return calls.map((tc, i) => {
    const toolUseId = (tc as any).tool_use_id || ''
    const result = resultMap.get(toolUseId)
    return {
      index: i + 1,
      name: tc.name,
      target: tc.target,
      is_error: result?.is_error ?? false,
      snippet: result?.snippet ?? '',
    }
  })
})
</script>

<template>
  <div class="result-view">
    <!-- Result text (prominent) -->
    <div v-if="execution.result_text" class="result-text-section">
      <h4>Result</h4>
      <MarkdownView :content="execution.result_text" />
    </div>

    <!-- Stats chips -->
    <div class="result-chips">
      <span class="chip">{{ formatDuration(execution.duration_seconds) }}</span>
      <span class="chip">{{ execution.files_changed.length }} files</span>
      <span class="chip">{{ execution.tool_calls_count }} tool calls</span>
    </div>

    <!-- Files changed -->
    <div v-if="execution.files_changed.length" class="files-section">
      <h4>Files Changed</h4>
      <div class="file-tags">
        <span v-for="f in execution.files_changed" :key="f" class="file-tag">{{ f }}</span>
      </div>
    </div>

    <!-- Tool timeline (collapsible) -->
    <div v-if="toolTimeline.length" class="timeline-section">
      <button class="section-toggle" @click="showToolTimeline = !showToolTimeline">
        <span>Tool Calls ({{ toolTimeline.length }})</span>
        <span class="toggle-arrow">{{ showToolTimeline ? '\u25BC' : '\u25B6' }}</span>
      </button>
      <div v-if="showToolTimeline" class="timeline-list">
        <div v-for="tc in toolTimeline" :key="tc.index" class="timeline-item">
          <span class="tl-index">{{ tc.index }}.</span>
          <span class="tl-name">{{ tc.name }}</span>
          <span class="tl-target">{{ tc.target }}</span>
          <span class="tl-status" :class="{ error: tc.is_error }">
            {{ tc.is_error ? '\u2717' : '\u2713' }}
          </span>
          <div v-if="tc.is_error && tc.snippet" class="tl-snippet">{{ tc.snippet }}</div>
        </div>
      </div>
    </div>

    <!-- Raw output (collapsible) -->
    <div v-if="execution.output" class="raw-section">
      <button class="section-toggle" @click="showRawOutput = !showRawOutput">
        <span>Raw Output ({{ execution.output.length }} chars)</span>
        <span class="toggle-arrow">{{ showRawOutput ? '\u25BC' : '\u25B6' }}</span>
      </button>
      <pre v-if="showRawOutput" class="raw-output">{{ execution.output }}</pre>
    </div>
  </div>
</template>

<style scoped>
.result-view {
  padding: 0;
}
.result-text-section {
  margin-bottom: 1rem;
  padding: 1rem;
  background: var(--green-bg);
  border-radius: var(--radius);
  border: 1px solid rgba(74, 124, 89, 0.2);
}
.result-text-section h4 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #3A6347;
  margin-bottom: 0.5rem;
}
.result-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 1rem;
}
.chip {
  font-size: 0.75rem;
  font-weight: 600;
  background: var(--surface-hover);
  color: var(--text-secondary);
  padding: 3px 10px;
  border-radius: 12px;
}
.files-section {
  margin-bottom: 1rem;
}
.files-section h4 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin-bottom: 0.375rem;
}
.file-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.file-tag {
  display: inline-block;
  background: var(--surface-hover);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--accent);
}
.section-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  background: none;
  border: none;
  padding: 0.5rem 0;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 0.8125rem;
  font-weight: 600;
  font-family: var(--font-sans);
  border-top: 1px solid var(--border);
}
.section-toggle:hover {
  color: var(--text);
}
.toggle-arrow {
  font-size: 0.625rem;
}
.timeline-section, .raw-section {
  margin-bottom: 0.5rem;
}
.timeline-list {
  padding: 0.5rem 0;
}
.timeline-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  padding: 3px 0;
  flex-wrap: wrap;
}
.tl-index {
  color: var(--muted);
  min-width: 24px;
  font-variant-numeric: tabular-nums;
}
.tl-name {
  color: var(--accent);
  font-weight: 600;
  min-width: 48px;
}
.tl-target {
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.tl-status {
  color: var(--green);
  font-weight: 700;
}
.tl-status.error {
  color: var(--red);
}
.tl-snippet {
  width: 100%;
  padding-left: 24px;
  color: var(--red);
  font-size: 0.6875rem;
  font-family: var(--font-mono);
}
.raw-output {
  background: #F0EBE4;
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  overflow-x: auto;
  white-space: pre-wrap;
  max-height: 300px;
  overflow-y: auto;
  color: var(--text-secondary);
  margin-top: 0.5rem;
}
</style>
