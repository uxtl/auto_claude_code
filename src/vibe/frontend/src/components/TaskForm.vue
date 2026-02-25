<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  submit: [description: string, depends?: number[]]
  batch: [action: string]
}>()

const text = ref('')
const dependsText = ref('')
const showMenu = ref(false)

function parseDeps(raw: string): number[] {
  if (!raw.trim()) return []
  return raw.split(',')
    .map(s => parseInt(s.trim(), 10))
    .filter(n => !isNaN(n) && n > 0)
}

function onSubmit() {
  const val = text.value.trim()
  if (!val) return
  const deps = parseDeps(dependsText.value)
  emit('submit', val, deps.length > 0 ? deps : undefined)
  text.value = ''
  dependsText.value = ''
}

function doBatch(action: string) {
  showMenu.value = false
  emit('batch', action)
}
</script>

<template>
  <form class="task-form" @submit.prevent="onSubmit">
    <div class="form-fields">
      <textarea
        v-model="text"
        placeholder="Enter task description (supports markdown)..."
        rows="2"
      ></textarea>
      <input
        v-model="dependsText"
        class="depends-input"
        placeholder="Depends on (e.g. 1,2)"
        type="text"
      />
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-success">Add</button>
      <div class="menu-wrap">
        <button type="button" class="btn btn-ghost btn-sm" @click="showMenu = !showMenu">...</button>
        <div v-if="showMenu" class="batch-menu" @click="showMenu = false">
          <button @click="doBatch('retry-all-failed')">Retry All Failed</button>
          <button @click="doBatch('clear-done')">Clear Done</button>
          <button @click="doBatch('recover')">Recover Running</button>
        </div>
      </div>
    </div>
  </form>
</template>

<style scoped>
.task-form {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
  padding: 0.75rem 1rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.form-fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}
textarea {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 8px 12px;
  font-size: 0.875rem;
  font-family: var(--font-sans);
  resize: vertical;
  min-height: 44px;
  line-height: 1.5;
}
textarea:focus {
  outline: none;
  border-color: var(--accent);
}
.depends-input {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 4px 12px;
  font-size: 0.75rem;
  font-family: var(--font-mono);
  line-height: 1.5;
}
.depends-input:focus {
  outline: none;
  border-color: var(--accent);
}
.form-actions {
  display: flex;
  gap: 0.375rem;
  align-items: flex-end;
}
.menu-wrap {
  position: relative;
}
.batch-menu {
  position: absolute;
  right: 0;
  bottom: 100%;
  margin-bottom: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-md);
  z-index: 50;
  min-width: 160px;
  overflow: hidden;
}
.batch-menu button {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 8px 12px;
  font-size: 0.8125rem;
  color: var(--text);
  cursor: pointer;
  font-family: var(--font-sans);
}
.batch-menu button:hover {
  background: var(--surface-hover);
}
</style>
