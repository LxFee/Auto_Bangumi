<script lang="ts" setup>
import { NTooltip } from 'naive-ui';

// NTooltip 的统一封装：延迟、触屏回退（点击触发）与样式只在这里定一次。
withDefaults(
  defineProps<{
    content?: string;
    placement?:
      | 'top'
      | 'bottom'
      | 'left'
      | 'right'
      | 'top-start'
      | 'top-end'
      | 'bottom-start'
      | 'bottom-end';
    delay?: number;
  }>(),
  {
    content: '',
    placement: 'top',
    delay: 400,
  }
);
const hovered = ref(false);
const focused = ref(false);
const pinned = ref(false);
const visible = computed(() => hovered.value || focused.value || pinned.value);

function togglePinned() {
  if (pinned.value) {
    close();
  } else {
    pinned.value = true;
  }
}

function close() {
  hovered.value = false;
  focused.value = false;
  pinned.value = false;
}
</script>

<template>
  <NTooltip
    :show="visible"
    :placement="placement"
    :delay="delay"
    trigger="manual"
  >
    <template #trigger>
      <span
        class="ab-tooltip-trigger"
        @mouseenter="hovered = true"
        @mouseleave="hovered = false"
        @focusin="focused = true"
        @focusout="focused = false"
        @click="togglePinned"
        @keydown.esc.stop="close"
      >
        <slot />
      </span>
    </template>
    <slot name="content">{{ content }}</slot>
  </NTooltip>
</template>

<style scoped>
.ab-tooltip-trigger {
  display: inline-flex;
}
</style>
