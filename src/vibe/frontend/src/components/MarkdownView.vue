<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ content: string }>()

const html = computed(() => {
  try {
    return marked(props.content, { breaks: true })
  } catch {
    return props.content
  }
})
</script>

<template>
  <div class="markdown-body" v-html="html"></div>
</template>
