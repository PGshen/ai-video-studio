/**
 * 新增音色表单的纯逻辑（计划 tts-voice-management T4）：校验规则与后端
 * `db/repo/voices.py::_validate` 一致（后端是最终裁判），表单值 ↔ 请求体的转换。
 */

import type { VoiceCreate, VoiceOut } from '@/types/api'

export interface VoiceFormValues {
  label: string
  alias: string
  speaker_id: string
  gender: 'female' | 'male'
  engine: 'doubao_1.0' | 'doubao_2.0'
}

export type VoiceFormErrors = Partial<Record<keyof VoiceFormValues, string>>

/** 豆包 TTS 版本：资源 id 与音色 id 的后缀系列都不同，选错会合成失败。 */
export const VOICE_ENGINES = [
  { value: 'doubao_1.0', label: '豆包 v1', hint: '音色 id 形如 zh_female_xxx_moon_bigtts' },
  { value: 'doubao_2.0', label: '豆包 v2', hint: '音色 id 形如 zh_female_xxx_uranus_bigtts' },
] as const

const ALIAS_PATTERN = /^[a-z0-9_]{1,40}$/
const SPEAKER_ID_PATTERN = /^[A-Za-z0-9_.-]{1,200}$/

export function emptyVoiceForm(): VoiceFormValues {
  return { label: '', alias: '', speaker_id: '', gender: 'female', engine: 'doubao_2.0' }
}

export function engineLabel(engine: string): string {
  return VOICE_ENGINES.find((item) => item.value === engine)?.label ?? engine
}

export function validateVoiceForm(
  values: VoiceFormValues,
  existing: readonly Pick<VoiceOut, 'alias'>[] = [],
): VoiceFormErrors {
  const errors: VoiceFormErrors = {}
  if (!values.label.trim()) errors.label = '名称不能为空'
  if (!ALIAS_PATTERN.test(values.alias)) {
    errors.alias = '别名只允许小写字母、数字和下划线，1–40 个字符'
  } else if (existing.some((voice) => voice.alias === values.alias)) {
    errors.alias = '别名已被占用'
  }
  if (!SPEAKER_ID_PATTERN.test(values.speaker_id)) {
    errors.speaker_id = 'speaker id 只允许字母、数字、下划线、点和连字符，不能为空'
  }
  return errors
}

export function toVoiceCreate(values: VoiceFormValues): VoiceCreate {
  return {
    alias: values.alias,
    label: values.label.trim(),
    gender: values.gender,
    speaker_id: values.speaker_id,
    engine: values.engine,
  }
}
