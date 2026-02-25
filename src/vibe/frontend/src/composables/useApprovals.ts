import { ref, onMounted, onUnmounted } from 'vue'
import { get, post } from '../api/client'

export interface ApprovalItem {
  approval_id: string
  task_name: string
  worker_id: string
  plan_text: string
  created_at: string
}

export function useApprovals() {
  const approvals = ref<ApprovalItem[]>([])
  let timer: ReturnType<typeof setInterval> | null = null
  let notified = new Set<string>()

  async function refresh() {
    try {
      approvals.value = await get<ApprovalItem[]>('/api/approvals')
      // Browser notifications for new approvals
      for (const a of approvals.value) {
        if (!notified.has(a.approval_id)) {
          notified.add(a.approval_id)
          notify(a)
        }
      }
    } catch { /* ignore */ }
  }

  function notify(a: ApprovalItem) {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Vibe: Plan Awaiting Approval', {
        body: `Task: ${a.task_name} (Worker: ${a.worker_id})`,
      })
    }
  }

  function requestNotifications() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  async function approve(id: string, feedback: string = '', selections: Record<string, string> = {}) {
    await post(`/api/approvals/${id}/approve`, { feedback, selections })
    await refresh()
  }

  async function reject(id: string) {
    await post(`/api/approvals/${id}/reject`)
    await refresh()
  }

  onMounted(() => {
    requestNotifications()
    refresh()
    timer = setInterval(refresh, 3000)
  })

  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { approvals, refresh, approve, reject }
}
