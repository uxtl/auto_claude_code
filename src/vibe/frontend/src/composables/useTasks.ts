import { ref, computed, onMounted, onUnmounted } from 'vue'
import { get, post, put, del } from '../api/client'

export interface TaskItem {
  name: string
  status: 'pending' | 'running' | 'done' | 'failed'
  file: string
  worker?: string
  description?: string
  depends?: number[]
  blocked?: boolean
  unmet_deps?: number[]
}

export interface TaskDetail {
  name: string
  status: string
  raw_content: string
  clean_content: string
  errors: string[]
  diagnostics: string[]
  retry_count: number
  file: string
  modified_at: number
}

export function useTasks() {
  const tasks = ref<TaskItem[]>([])
  let timer: ReturnType<typeof setInterval> | null = null

  const counts = computed(() => {
    const c = { pending: 0, running: 0, done: 0, failed: 0, blocked: 0 }
    for (const t of tasks.value) {
      if (t.status in c) c[t.status as keyof typeof c]++
      if (t.blocked) c.blocked++
    }
    return c
  })

  async function refresh() {
    try {
      tasks.value = await get<TaskItem[]>('/api/tasks')
    } catch { /* ignore */ }
  }

  async function addTask(description: string, depends?: number[]) {
    const body: Record<string, unknown> = { description }
    if (depends && depends.length > 0) body.depends = depends
    await post('/api/tasks', body)
    await refresh()
  }

  async function forceRunTask(name: string) {
    await post(`/api/tasks/${encodeURIComponent(name)}/force-run`)
    await refresh()
  }

  async function deleteTask(name: string) {
    await del(`/api/tasks/${encodeURIComponent(name)}`)
    await refresh()
  }

  async function retryTask(name: string) {
    await post(`/api/tasks/${encodeURIComponent(name)}/retry`)
    await refresh()
  }

  async function getContent(name: string): Promise<TaskDetail> {
    return get<TaskDetail>(`/api/tasks/${encodeURIComponent(name)}/content`)
  }

  async function updateContent(name: string, content: string) {
    await put(`/api/tasks/${encodeURIComponent(name)}/content`, { content })
    await refresh()
  }

  async function batchAction(action: string) {
    await post(`/api/tasks/batch/${action}`)
    await refresh()
  }

  onMounted(() => {
    refresh()
    timer = setInterval(refresh, 5000)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { tasks, counts, refresh, addTask, deleteTask, retryTask, forceRunTask, getContent, updateContent, batchAction }
}
