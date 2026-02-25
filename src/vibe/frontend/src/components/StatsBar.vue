<script setup lang="ts">
defineProps<{
  pending: number
  running: number
  done: number
  failed: number
  awaiting: number
  blocked: number
}>()
</script>

<template>
  <div class="stats-bar">
    <span class="stat-pill" style="--pill-bg: var(--yellow-bg); --pill-color: #8B6914">
      Pending <strong>{{ pending }}</strong>
    </span>
    <span v-if="blocked > 0" class="stat-pill" style="--pill-bg: #FEF3C7; --pill-color: #92400E">
      Blocked <strong>{{ blocked }}</strong>
    </span>
    <span class="stat-pill" style="--pill-bg: var(--blue-bg); --pill-color: #3A5A8C">
      Running <strong>{{ running }}</strong>
    </span>
    <span v-if="awaiting > 0" class="stat-pill" style="--pill-bg: var(--purple-bg); --pill-color: #634A8A">
      Review <strong>{{ awaiting }}</strong>
    </span>
    <span class="stat-pill" style="--pill-bg: var(--green-bg); --pill-color: #3A6347">
      Done <strong>{{ done }}</strong>
    </span>
    <span class="stat-pill" style="--pill-bg: var(--red-bg); --pill-color: #9B3728">
      Failed <strong>{{ failed }}</strong>
    </span>
  </div>
</template>

<style scoped>
.stats-bar {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  flex-wrap: wrap;
}
.stat-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--pill-bg);
  color: var(--pill-color);
  white-space: nowrap;
}
.stat-pill strong {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
</style>
