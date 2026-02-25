import { ref, onMounted } from 'vue'
import { get } from '../api/client'

export interface VibeConfig {
  task_dir: string
  done_dir: string
  fail_dir: string
  timeout: number
  max_retries: number
  max_workers: number
  workspace: string
  log_level: string
  log_file: string
  use_worktree: boolean
  plan_mode: boolean
  plan_auto_approve: boolean
  use_docker: boolean
  docker_image: string
  docker_extra_args: string
  poll_interval: number
  verbose: boolean
}

export function useConfig() {
  const config = ref<VibeConfig | null>(null)

  async function load() {
    try {
      config.value = await get<VibeConfig>('/api/config')
    } catch { /* ignore */ }
  }

  onMounted(load)

  return { config, load }
}
