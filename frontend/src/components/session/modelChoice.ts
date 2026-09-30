/**
 * 会话内换模型与新建会话预选模型的纯逻辑（计划 M5 T12，ADR 0012）。
 *
 * 换模型的规则与后端 `api/sessions.py::switch_session_model_endpoint` 一致（后端是最终裁判，
 * 这里只是让不可选的选项提前灰掉并说明原因）：同 `runtime` 且同 `provider`、目标密钥已配置；
 * Claude 运行时另外要求同一种认证方式（`api_key_env` 相同）——本机登录 ↔ API key 互换没有验证过
 * （TD-41）。
 */

import type { ModelProfileOut } from '@/types/api'

export interface SwitchOption {
  profile: ModelProfileOut
  /** 不能选时的原因；`null` 表示可选。当前配置本身可选（选它等于没换）。 */
  disabledReason: string | null
}

function reasonFor(current: ModelProfileOut | undefined, target: ModelProfileOut): string | null {
  if (!current) return '会话当前的模型配置已不存在，请新建会话'
  if (target.id === current.id) return null
  if (target.runtime !== current.runtime) {
    return `运行时不同（${current.runtime} → ${target.runtime}），请新建会话`
  }
  if (target.provider !== current.provider) {
    return `供应商不同（${current.provider} → ${target.provider}），请新建会话`
  }
  if (current.runtime === 'claude' && target.api_key_env !== current.api_key_env) {
    return '认证方式不同（本机登录与 API key 之间不能互换，尚未验证）'
  }
  if (!target.key_configured) return '密钥未配置'
  return null
}

export function switchOptions(
  current: ModelProfileOut | undefined,
  all: ModelProfileOut[],
): SwitchOption[] {
  return all.map((profile) => ({ profile, disabledReason: reasonFor(current, profile) }))
}

/** 会话正在运行时不能换（后端对排队中的 turn 也会拒绝，返回 409，界面原样显示）。 */
export function switchBlockedReason(sessionStatus: string): string | null {
  return sessionStatus === 'running' ? '会话正在运行，这一轮结束后才能换模型' : null
}

/**
 * 新建会话时预选哪个配置：该阶段的默认模型（仍存在且密钥已配置）→ 第一个已配置的 → 第一个 →
 * 空字符串（列表为空）。
 */
export function preselectProfileId(
  profiles: ModelProfileOut[],
  stageDefaults: Record<string, string>,
  stage: string,
): string {
  const preferred = profiles.find((p) => p.id === stageDefaults[stage])
  if (preferred?.key_configured) return preferred.id
  const configured = profiles.find((p) => p.key_configured)
  return (configured ?? profiles[0])?.id ?? ''
}
