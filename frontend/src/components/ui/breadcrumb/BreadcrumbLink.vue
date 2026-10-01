<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { cn } from "@/lib/utils"

const props = defineProps<{
  class?: HTMLAttributes["class"]
  /** 传入时渲染为 router-link；不传则渲染 <a>（配合 default slot）。 */
  to?: string
}>()
</script>

<template>
  <router-link
    v-if="props.to"
    data-slot="breadcrumb-link"
    :to="props.to"
    :class="cn('hover:text-foreground transition-colors', props.class)"
  >
    <slot />
  </router-link>
  <a
    v-else
    data-slot="breadcrumb-link"
    :class="cn('hover:text-foreground transition-colors', props.class)"
  >
    <slot />
  </a>
</template>
