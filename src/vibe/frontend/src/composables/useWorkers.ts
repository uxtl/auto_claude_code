import { ref, onMounted, onUnmounted } from 'vue'
import { get } from '../api/client'

export interface WorkerStatus {
  worker_id: string
  phase: string
  task: string | null
  cwd?: string
  started_at?: number
}

export function useWorkers() {
  const workers = ref<Record<string, WorkerStatus>>({})
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh() {
    try {
      workers.value = await get<Record<string, WorkerStatus>>('/api/workers')
    } catch { /* ignore */ }
  }

  onMounted(() => {
    refresh()
    timer = setInterval(refresh, 3000)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { workers, refresh }
}
