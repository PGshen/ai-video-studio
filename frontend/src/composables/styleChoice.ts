/**
 * 创建项目时「选风格」的共用逻辑（计划 M5 T11）：项目页的新建表单和选题池的「创建项目」
 * 对话框都用它，控件是 `components/StyleSelect.vue`。
 *
 * 选择器的值是风格 id；空字符串表示「不指定」——请求里不带 `style_preset_id`，服务端会用默认
 * 风格，没有默认风格时用占位 `STYLE.md`。
 */

import type { StyleSummaryOut } from '@/types/api'

/** 预选值：有默认风格就是它，否则空字符串（不指定）。 */
export function initialStyleId(presets: StyleSummaryOut[]): string {
  return presets.find((p) => p.is_default)?.id ?? ''
}

export function styleOptionLabel(preset: StyleSummaryOut): string {
  return preset.is_default ? `${preset.name}（默认）` : preset.name
}

export interface StyleOption {
  value: string
  label: string
}

/** 下拉的选项：第一项是「不指定」，之后是各预设。 */
export function styleSelectOptions(presets: StyleSummaryOut[]): StyleOption[] {
  return [
    { value: '', label: '不指定（用默认风格；没有默认风格时用占位）' },
    ...presets.map((p) => ({ value: p.id, label: styleOptionLabel(p) })),
  ]
}

/** 请求里的 `style_preset_id`：空字符串不发。 */
export function styleIdForRequest(value: string): string | undefined {
  return value === '' ? undefined : value
}
