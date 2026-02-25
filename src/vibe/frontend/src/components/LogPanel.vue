<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { LogEntry } from '../composables/useLogs'

const props = defineProps<{
  logs: LogEntry[]
  connected: boolean
  filterWorker: string
  filterText: string
}>()

const emit = defineEmits<{
  'update:filterWorker': [val: string]
  'update:filterText': [val: string]
  clear: []
  download: []
}>()

const autoScroll = ref(true)
const collapsed = ref(false)
const panelHeight = ref(250)
const logContainer = ref<HTMLElement | null>(null)
const resizing = ref(false)

// Discover workers from logs
const workerIds = computed(() => {
  const ids = new Set<string>()
  for (const l of props.logs) {
    if (l.worker) ids.add(l.worker)
  }
  return Array.from(ids).sort()
})

// Filter logs
const filtered = computed(() => {
  return props.logs.filter(l => {
    if (props.filterWorker && l.worker !== props.filterWorker) return false
    if (props.filterText && !l.text.toLowerCase().includes(props.filterText.toLowerCase())) return false
    return true
  })
})

// Auto-scroll
watch(filtered, async () => {
  if (autoScroll.value && logContainer.value) {
    await nextTick()
    logContainer.value.scrollTop = logContainer.value.scrollHeight
  }
})

// Level colors
function levelClass(level: string): string {
  switch (level) {
    case 'error': return 'log-error'
    case 'warning': return 'log-warning'
    default: return ''
  }
}

function colorize(text: string): string {
  if (text.includes('\u{1F527}')) return 'log-tool'
  if (text.includes('\u2705')) return 'log-success'
  return ''
}

// Resize handle
function startResize(e: MouseEvent) {
  resizing.value = true
  const startY = e.clientY
  const startH = panelHeight.value
  function onMove(ev: MouseEvent) {
    panelHeight.value = Math.max(100, Math.min(600, startH - (ev.clientY - startY)))
  }
  function onUp() {
    resizing.value = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}
</script>

<template>
  <div class="log-panel" :style="{ height: collapsed ? '36px' : panelHeight + 'px' }">
    <div class="log-resize" @mousedown="startResize" v-if="!collapsed"></div>
    <div class="log-toolbar">
      <div class="log-filters">
        <button
          class="filter-btn"
          :class="{ active: !filterWorker }"
          @click="emit('update:filterWorker', '')"
        >All</button>
        <button
          v-for="w in workerIds"
          :key="w"
          class="filter-btn"
          :class="{ active: filterWorker === w }"
          @click="emit('update:filterWorker', w)"
        >{{ w }}</button>
      </div>
      <input
        type="text"
        class="log-search"
        placeholder="Search..."
        :value="filterText"
        @input="emit('update:filterText', ($event.target as HTMLInputElement).value)"
      >
      <div class="log-controls">
        <label class="auto-scroll-label">
          <input type="checkbox" v-model="autoScroll"> Auto
        </label>
        <span class="conn-dot" :class="{ online: connected }"></span>
        <button class="btn btn-ghost btn-sm" @click="emit('clear')">Clear</button>
        <button class="btn btn-ghost btn-sm" @click="emit('download')">Export</button>
        <button class="btn btn-ghost btn-sm" @click="collapsed = !collapsed">
          {{ collapsed ? 'Logs' : 'Hide' }}
        </button>
      </div>
    </div>
    <div v-if="!collapsed" ref="logContainer" class="log-content">
      <div
        v-for="l in filtered"
        :key="l.id"
        class="log-line"
        :class="[levelClass(l.level), colorize(l.text)]"
      >{{ l.text }}</div>
    </div>
  </div>
</template>

<style scoped>
.log-panel {
  border-top: 1px solid var(--border);
  background: #2C2420;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: relative;
  transition: height 0.15s ease;
}
.log-resize {
  position: absolute;
  top: -3px;
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
  z-index: 10;
}
.log-resize:hover {
  background: var(--accent);
  opacity: 0.3;
}
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 4px 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex-shrink: 0;
  min-height: 36px;
  background: #2C2420;
}
.log-filters {
  display: flex;
  gap: 2px;
}
.filter-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 4px;
  color: #B8A898;
  font-size: 0.6875rem;
  padding: 2px 8px;
  cursor: pointer;
  font-family: var(--font-mono);
  transition: all var(--transition);
}
.filter-btn:hover { color: #E2E8F0; }
.filter-btn.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.log-search {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 4px;
  color: #E5DED5;
  font-size: 0.75rem;
  padding: 3px 8px;
  width: 140px;
  font-family: var(--font-sans);
}
.log-search:focus {
  outline: none;
  border-color: var(--accent);
}
.log-search::placeholder {
  color: #8B7D6E;
}
.log-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}
.log-controls .btn-ghost {
  color: #B8A898;
  border-color: rgba(255, 255, 255, 0.15);
}
.log-controls .btn-ghost:hover {
  color: #E5DED5;
  background: rgba(255, 255, 255, 0.08);
}
.auto-scroll-label {
  font-size: 0.6875rem;
  color: #B8A898;
  display: flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
}
.conn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #C44536;
}
.conn-dot.online {
  background: #4A7C59;
}
.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.4;
}
/* Dark scrollbar for log panel */
.log-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
}
.log-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}
.log-line {
  color: #B8A898;
  white-space: pre-wrap;
  word-break: break-all;
  padding: 0 4px;
}
.log-error {
  color: #E07060;
  background: rgba(196, 69, 54, 0.1);
}
.log-warning {
  color: #D4A843;
}
.log-tool {
  color: #7BA1C7;
}
.log-success {
  color: #6BAF7D;
}
</style>
