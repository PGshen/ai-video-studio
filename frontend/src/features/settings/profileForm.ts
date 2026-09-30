/**
 * 模型配置表单的纯逻辑（计划 M5 T10）：校验规则和后端 `db/repo/profiles.py::_validate_profile`
 * 保持一致（后端是最终裁判，这里只是让使用者提交前就看到问题），表单值 ↔ 请求体的转换。
 *
 * 表单里数字输入都是字符串（`<input>` 的值），空字符串表示「留空 = 不限/没有」。
 */

import type { ModelProfileCreate, ModelProfileOut, ModelProfilePatch } from '@/types/api'

export interface ProfileFormValues {
  name: string
  provider: string
  model: string
  runtime: string
  base_url: string
  api_key_env: string
  supports_vision: boolean
  price_input: string
  price_output: string
  max_cost_per_turn: string
  max_steps_per_turn: string
}

export type ProfileFormErrors = Partial<Record<keyof ProfileFormValues, string>>

/** 界面里可以新建的运行时（`fake` 只用于测试）。 */
export const USER_RUNTIMES = ['claude', 'openai'] as const

const NAME_PATTERN = /^[\p{L}\p{N}_.-]{1,50}$/u
const ENV_NAME_PATTERN = /^[A-Z_][A-Z0-9_]*$/

export function emptyProfileForm(): ProfileFormValues {
  return {
    name: '',
    provider: 'openai',
    model: '',
    runtime: 'openai',
    base_url: '',
    api_key_env: '',
    supports_vision: false,
    price_input: '',
    price_output: '',
    max_cost_per_turn: '',
    max_steps_per_turn: '',
  }
}

function text(value: number | null): string {
  return value === null ? '' : String(value)
}

export function formFromProfile(profile: ModelProfileOut): ProfileFormValues {
  return {
    name: profile.name,
    provider: profile.provider,
    model: profile.model,
    runtime: profile.runtime,
    base_url: profile.base_url ?? '',
    api_key_env: profile.api_key_env ?? '',
    supports_vision: profile.supports_vision,
    price_input: text(profile.price_input),
    price_output: text(profile.price_output),
    max_cost_per_turn: text(profile.max_cost_per_turn),
    max_steps_per_turn: text(profile.max_steps_per_turn),
  }
}

/** 空字符串 → `null`；否则解析成有限数字，解析不了返回 `NaN`（由校验报错）。 */
function parseNumber(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  return /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(trimmed) ? Number(trimmed) : Number.NaN
}

function nonNegative(value: string): boolean {
  const parsed = parseNumber(value)
  return parsed === null || (Number.isFinite(parsed) && parsed >= 0)
}

function validBaseUrl(value: string): 'ok' | 'scheme' | 'credentials' {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return 'scheme'
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return 'scheme'
  if (url.username || url.password) return 'credentials'
  return 'ok'
}

/**
 * `mode === 'edit'` 时不检查 `name`/`provider`/`runtime`（建好后不可改）。
 * 返回 `{字段: 中文错误}`，没有错误返回 `{}`。
 */
export function validateProfileForm(
  values: ProfileFormValues,
  mode: 'create' | 'edit',
): ProfileFormErrors {
  const errors: ProfileFormErrors = {}
  if (mode === 'create') {
    if (!NAME_PATTERN.test(values.name)) {
      errors.name = '名称只允许字母、数字、下划线、点和连字符，1–50 个字符'
    }
    if (!values.provider.trim()) errors.provider = 'provider 不能为空'
    if (!(USER_RUNTIMES as readonly string[]).includes(values.runtime)) {
      errors.runtime = `运行时必须是 ${USER_RUNTIMES.join(' / ')}`
    }
  }
  if (!values.model.trim()) errors.model = '模型名不能为空'

  const baseUrl = values.base_url.trim()
  if (baseUrl) {
    const result = validBaseUrl(baseUrl)
    if (result === 'scheme') errors.base_url = 'base_url 必须是 http(s) 地址'
    if (result === 'credentials') {
      errors.base_url = 'base_url 不能包含账号密码（密钥请放在环境变量里）'
    }
  }

  const keyEnv = values.api_key_env.trim()
  if (!keyEnv) {
    if (values.runtime !== 'claude' && values.runtime !== 'fake') {
      errors.api_key_env = '只有 claude 运行时可以不填 API key 环境变量（使用本机登录）'
    }
  } else if (!ENV_NAME_PATTERN.test(keyEnv)) {
    errors.api_key_env = '要填环境变量的名字（大写字母、数字、下划线），不是 key 本身'
  }

  if (!nonNegative(values.price_input)) errors.price_input = '单价必须是非负数字，或留空'
  if (!nonNegative(values.price_output)) errors.price_output = '单价必须是非负数字，或留空'
  if (!nonNegative(values.max_cost_per_turn)) {
    errors.max_cost_per_turn = '单轮成本上限必须是非负数字，或留空表示不限'
  }
  const steps = parseNumber(values.max_steps_per_turn)
  if (steps !== null && !(Number.isInteger(steps) && steps >= 1)) {
    errors.max_steps_per_turn = '单轮步数上限必须是正整数，或留空表示不限'
  }
  return errors
}

function nullable(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function numeric(value: string): number | null {
  return parseNumber(value)
}

export function toCreateBody(values: ProfileFormValues): ModelProfileCreate {
  return {
    name: values.name.trim(),
    provider: values.provider.trim(),
    model: values.model.trim(),
    runtime: values.runtime,
    base_url: nullable(values.base_url),
    api_key_env: nullable(values.api_key_env),
    supports_vision: values.supports_vision,
    price_input: numeric(values.price_input),
    price_output: numeric(values.price_output),
    max_cost_per_turn: numeric(values.max_cost_per_turn),
    max_steps_per_turn: numeric(values.max_steps_per_turn),
  }
}

/** 只含改过的字段；环境变量决定的字段（`env_override`）一律不发，后端会拒绝。 */
export function toPatchBody(
  values: ProfileFormValues,
  original: ModelProfileOut,
): ModelProfilePatch {
  const target = toCreateBody(values)
  const patch: ModelProfilePatch = {}
  const fields = [
    'model',
    'base_url',
    'api_key_env',
    'supports_vision',
    'price_input',
    'price_output',
    'max_cost_per_turn',
    'max_steps_per_turn',
  ] as const
  for (const field of fields) {
    if (original.env_override.includes(field)) continue
    if (target[field] !== original[field]) {
      // 逐字段赋值：各字段类型不同，TypeScript 需要在这里放宽一次。
      ;(patch as Record<string, unknown>)[field] = target[field]
    }
  }
  return patch
}

/** 单轮成本上限为 0 时，后端会让每一轮都在开始前被拒绝（TD-12），这里提前提醒。 */
export function zeroBudgetWarning(values: ProfileFormValues): string | null {
  return numeric(values.max_cost_per_turn) === 0
    ? '成本上限为 0 会让每一轮都被拒绝，想不限制请留空'
    : null
}
