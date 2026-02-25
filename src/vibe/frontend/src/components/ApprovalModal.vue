<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { ApprovalItem } from '../composables/useApprovals'
import MarkdownView from './MarkdownView.vue'

const props = defineProps<{
  approval: ApprovalItem | null
}>()

const emit = defineEmits<{
  approve: [id: string, feedback: string, selections: Record<string, string>]
  reject: [id: string]
  close: []
}>()

const feedback = ref('')
const selections = ref<Record<string, string>>({})

// Parse questions from plan text
interface PlanQuestion {
  id: string
  text: string
  options: string[]
}

const questions = computed<PlanQuestion[]>(() => {
  if (!props.approval) return []
  const text = props.approval.plan_text
  const qs: PlanQuestion[] = []

  // Pattern 1: **问题:** or **Q:**
  const questionPattern = /\*\*(问题|Q|Question)\s*\d*[.:：]\*?\*?\s*(.+?)(?=\n(?:\*\*|$|\n\n))/gi
  let match: RegExpExecArray | null
  let idx = 0

  // eslint-disable-next-line no-cond-assign
  while ((match = questionPattern.exec(text)) !== null) {
    const qText = match[2].trim()
    // Look for options after the question
    const afterQ = text.slice(match.index + match[0].length, match.index + match[0].length + 500)
    const optionMatches = afterQ.match(/- \[[ x]?\]\s*(.+)/g)
    const options: string[] = []
    if (optionMatches) {
      for (const om of optionMatches) {
        const optText = om.replace(/^- \[[ x]?\]\s*/, '').trim()
        if (optText) options.push(optText)
      }
    }
    // Also check [Option A] [Option B] pattern
    if (!options.length) {
      const pillMatches = afterQ.match(/\[([^\]]+)\]/g)
      if (pillMatches) {
        for (const pm of pillMatches) {
          const optText = pm.slice(1, -1).trim()
          if (optText && optText.length < 60) options.push(optText)
        }
      }
    }
    qs.push({ id: `q${idx++}`, text: qText, options })
  }

  return qs
})

watch(() => props.approval, () => {
  feedback.value = ''
  selections.value = {}
})

function selectOption(qId: string, opt: string) {
  selections.value = { ...selections.value, [qId]: opt }
}

function handleApprove() {
  if (!props.approval) return
  emit('approve', props.approval.approval_id, feedback.value, selections.value)
}

function handleReject() {
  if (!props.approval) return
  if (!confirm('Reject this plan? The task will be marked as failed.')) return
  emit('reject', props.approval.approval_id)
}
</script>

<template>
  <Teleport to="body">
    <template v-if="approval">
      <div class="modal-overlay" @click="emit('close')"></div>
      <div class="approval-modal">
        <!-- Header -->
        <div class="modal-header">
          <div class="modal-title-row">
            <span class="badge badge-review">Review</span>
            <h3>{{ approval.task_name }}</h3>
          </div>
          <button class="btn btn-ghost btn-sm" @click="emit('close')">Close</button>
        </div>

        <!-- Body -->
        <div class="modal-body">
          <!-- Plan text -->
          <div class="plan-section">
            <MarkdownView :content="approval.plan_text" />
          </div>

          <!-- Questions section -->
          <div v-if="questions.length" class="questions-section">
            <h4>Questions from Claude</h4>
            <div v-for="q in questions" :key="q.id" class="question-block">
              <div class="question-text">{{ q.text }}</div>
              <div v-if="q.options.length" class="question-options">
                <button
                  v-for="opt in q.options"
                  :key="opt"
                  class="option-pill"
                  :class="{ selected: selections[q.id] === opt }"
                  @click="selectOption(q.id, opt)"
                >{{ opt }}</button>
              </div>
            </div>
          </div>

          <!-- Feedback textarea -->
          <div class="feedback-section">
            <label class="feedback-label">Additional notes or modifications</label>
            <textarea
              v-model="feedback"
              class="feedback-textarea"
              rows="3"
              placeholder="Add notes, modifications, or instructions..."
            ></textarea>
          </div>
        </div>

        <!-- Footer -->
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="emit('close')">Cancel</button>
          <button class="btn btn-danger" @click="handleReject">Reject</button>
          <button class="btn btn-success" @click="handleApprove">Approve & Execute</button>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 200;
}
.approval-modal {
  position: fixed;
  top: 5%;
  left: 10%;
  right: 10%;
  bottom: 5%;
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);
  z-index: 201;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.modal-title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.modal-title-row h3 {
  font-size: 1rem;
  font-weight: 600;
}
.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}
.plan-section {
  margin-bottom: 1.5rem;
}
.questions-section {
  background: var(--blue-bg);
  border-radius: var(--radius);
  padding: 1rem;
  margin-bottom: 1.5rem;
}
.questions-section h4 {
  font-size: 0.875rem;
  font-weight: 600;
  color: #3A5A8C;
  margin-bottom: 0.75rem;
}
.question-block {
  margin-bottom: 1rem;
}
.question-block:last-child {
  margin-bottom: 0;
}
.question-text {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 0.5rem;
}
.question-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}
.option-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all var(--transition);
  color: var(--text-secondary);
  font-family: var(--font-sans);
}
.option-pill:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.option-pill.selected {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.feedback-section {
  margin-bottom: 1rem;
}
.feedback-label {
  display: block;
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 0.375rem;
}
.feedback-textarea {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 10px 12px;
  font-size: 0.875rem;
  font-family: var(--font-sans);
  resize: vertical;
  min-height: 70px;
  line-height: 1.5;
}
.feedback-textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.modal-footer {
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
</style>
