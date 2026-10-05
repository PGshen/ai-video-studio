<script setup lang="ts">
/** 配乐声明的事件表：点一行跳到事件起点。 */
import type { MusicEventOut } from '@/types/api'
import { formatClock } from './musicView'

defineProps<{ events: MusicEventOut[] }>()
const emit = defineEmits<{ seek: [seconds: number] }>()
</script>

<template>
  <p
    v-if="events.length === 0"
    class="text-muted-foreground text-sm"
    data-testid="events-empty"
  >
    脚本没有声明事件。
  </p>
  <table
    v-else
    class="w-full text-left text-sm"
    data-testid="events-table"
  >
    <thead class="text-muted-foreground text-xs">
      <tr>
        <th class="py-1 pr-3 font-normal">
          名称
        </th>
        <th class="py-1 pr-3 font-normal">
          类型
        </th>
        <th class="py-1 font-normal">
          起止
        </th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="(event, index) in events"
        :key="index"
        class="hover:bg-muted cursor-pointer"
        data-testid="event-row"
        @click="emit('seek', event.start)"
      >
        <td class="py-1 pr-3">
          {{ event.name }}
        </td>
        <td class="py-1 pr-3">
          {{ event.kind === 'sweep' ? '扫频' : '瞬发' }}
        </td>
        <td class="py-1 tabular-nums">
          {{ formatClock(event.start) }}
          <template v-if="event.kind === 'sweep'">
            – {{ formatClock(event.end) }}
          </template>
        </td>
      </tr>
    </tbody>
  </table>
</template>
