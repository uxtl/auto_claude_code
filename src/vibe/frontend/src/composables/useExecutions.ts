import { ref } from 'vue'
import { get } from '../api/client'

export interface ToolResultSummary {
  tool_use_id: string
  name: string
  is_error: boolean
  snippet: string
}

export interface Execution {
  id: number
  task_name: string
  worker_id: string
  success: boolean
  output: string
  error: string
  files_changed: string[]
  tool_calls_summary: { name: string; target: string; tool_use_id?: string }[]
  tool_calls_count: number
  duration_seconds: number
  return_code: number | null
  created_at: string
  result_text: string
  tool_results_summary: ToolResultSummary[]
}

export function useExecutions() {
  const executions = ref<Execution[]>([])
  const loading = ref(false)

  async function loadRecent(limit = 50) {
    loading.value = true
    try {
      executions.value = await get<Execution[]>(`/api/executions?limit=${limit}`)
    } catch { /* ignore */ } finally {
      loading.value = false
    }
  }

  async function loadByTask(taskName: string): Promise<Execution[]> {
    return get<Execution[]>(`/api/executions/${encodeURIComponent(taskName)}`)
  }

  async function loadById(id: number): Promise<Execution> {
    return get<Execution>(`/api/executions/detail/${id}`)
  }

  return { executions, loading, loadRecent, loadByTask, loadById }
}
