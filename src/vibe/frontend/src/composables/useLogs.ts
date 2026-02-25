import { ref, onMounted, onUnmounted } from 'vue'
import { createSSE } from '../api/client'

export interface LogEntry {
  id: number
  text: string
  level: string
  worker: string
}

let nextId = 0

function parseLevel(text: string): string {
  if (text.includes('[ERROR]')) return 'error'
  if (text.includes('[WARNING]')) return 'warning'
  if (text.includes('[INFO]')) return 'info'
  if (text.includes('[DEBUG]')) return 'debug'
  return 'info'
}

function parseWorker(text: string): string {
  const m = text.match(/\[(w\d+)\]/)
  return m ? m[1] : ''
}

export function useLogs() {
  const logs = ref<LogEntry[]>([])
  const connected = ref(false)
  const filterWorker = ref('')
  const filterText = ref('')
  let es: EventSource | null = null

  function connect() {
    es = createSSE(
      '/api/logs',
      (data) => {
        connected.value = true
        logs.value.push({
          id: nextId++,
          text: data,
          level: parseLevel(data),
          worker: parseWorker(data),
        })
        // Cap at 2000 entries
        if (logs.value.length > 2000) {
          logs.value = logs.value.slice(-1500)
        }
      },
      () => { connected.value = false },
    )
  }

  function clear() {
    logs.value = []
  }

  function download() {
    const text = logs.value.map(l => l.text).join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vibe-logs-${new Date().toISOString().slice(0, 19)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  onMounted(connect)
  onUnmounted(() => { if (es) es.close() })

  return { logs, connected, filterWorker, filterText, clear, download }
}
