<script setup lang="ts">
/**
 * “镜头 Beats”标签内容：选中镜头在叙事产物里的旁白、画面意图和 beats
 * （cue_text / visual_action / emphasis / transition），方便对照下面的代码。
 * 纯展示；数据来自 `narrativeScenes.ts::parseNarrativeScenes`。
 */
import type { NarrativeSceneInfo } from './narrativeScenes'

defineProps<{ scene: NarrativeSceneInfo | null }>()
</script>

<template>
  <div
    class="flex max-h-56 flex-col gap-2 overflow-y-auto text-sm"
    data-testid="scene-beats"
  >
    <p
      v-if="scene === null"
      class="text-muted-foreground text-xs"
    >
      叙事产物里没有找到这个镜头。
    </p>
    <template v-else>
      <p v-if="scene.narration">
        <span class="text-muted-foreground text-xs">旁白　</span>{{ scene.narration }}
      </p>
      <p v-if="scene.visualIntent">
        <span class="text-muted-foreground text-xs">画面意图　</span>{{ scene.visualIntent }}
      </p>
      <ol
        v-if="scene.beats.length"
        class="flex flex-col gap-1.5"
      >
        <li
          v-for="(beat, index) in scene.beats"
          :key="index"
          class="bg-muted/50 rounded border px-2 py-1.5"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="font-medium">{{ index + 1 }}. {{ beat.cueText }}</span>
            <span
              v-if="beat.transition"
              class="text-muted-foreground shrink-0 text-xs"
            >
              {{ beat.transition }}
            </span>
          </div>
          <p
            v-if="beat.visualAction"
            class="text-muted-foreground text-xs"
          >
            画面：{{ beat.visualAction }}
          </p>
          <p
            v-if="beat.emphasis"
            class="text-muted-foreground text-xs"
          >
            重点：{{ beat.emphasis }}
          </p>
        </li>
      </ol>
      <p
        v-else
        class="text-muted-foreground text-xs"
      >
        这个镜头还没有 beats。
      </p>
    </template>
  </div>
</template>
