/**
 * 设置页的纯逻辑（计划 M5 T10）：默认模型可选项、联网模式的来源文案与风险提示、
 * 环境变量锁定字段、key 状态。组件只负责渲染。
 */

import type { ModelProfileOut, SettingsOut, WebMode } from '@/types/api'

/** 「各阶段默认模型」要列出的阶段，顺序与流水线一致（头脑风暴在最前）。 */
export const DEFAULT_PROFILE_STAGES = [
  { key: 'brainstorm', label: '头脑风暴' },
  { key: 'topic', label: '选题' },
  { key: 'narrative', label: '叙事' },
  { key: 'animation', label: '动画' },
] as const

/**
 * 默认模型下拉的可选项：只列 key 已配置的（后端也会拒绝未配置的）；当前已选的即使已经
 * 不可用也保留在列表里，避免选项凭空消失、下拉显示成空白。
 */
export function defaultProfileChoices(
  profiles: ModelProfileOut[],
  currentId: string | null,
): ModelProfileOut[] {
  return profiles.filter((p) => p.key_configured || p.id === currentId)
}

export const WEB_MODE_LABELS: Record<WebMode, string> = {
  tools: '自建工具（默认）',
  native: '原生联网',
}

/** 不带「（默认）」的短名，用在句子里。 */
const WEB_MODE_SHORT: Record<WebMode, string> = {
  tools: '自建工具',
  native: '原生联网',
}

export const WEB_MODE_HINTS: Record<WebMode, string> = {
  tools:
    '头脑风暴和选题用自建的 web_search / fetch_url（Tavily，需要 TAVILY_API_KEY）。fetch_url 只能抓本会话搜索结果或你消息里出现过的 URL。',
  native:
    '用运行时自带的联网能力（Claude 的 WebSearch/WebFetch、OpenAI 的托管搜索），不需要 Tavily key。',
}

export function webModeSourceText(settings: SettingsOut): string {
  if (settings.web_mode_source === 'ui') {
    return `当前由界面设置；清除后回到环境变量 STUDIO_WEB_MODE 的值（${WEB_MODE_SHORT[settings.web_mode_env]}）`
  }
  return '当前来自环境变量 STUDIO_WEB_MODE（backend/.env），在这里选择会覆盖它'
}

/** 选了某个联网模式时要给使用者看的风险说明（ADR 0010；TD-39）。 */
export function webModeNotes(mode: WebMode): string[] {
  if (mode === 'tools') return []
  return [
    'Claude 的 WebFetch 仍受「URL 来源」规则约束，但 OpenAI 托管搜索在服务端执行，没有这层限制；提示注入的网页有可能诱导模型把内容外发到攻击者的 URL，风险由你自己承担（ADR 0010）。',
    'OpenAI 托管搜索经 OpenRouter 等非官方 base_url 是否可用尚未验证（TD-39）；用这类配置时联网可能不可用，会自动退回自建工具。',
  ]
}

export function isFieldLocked(profile: ModelProfileOut, field: string): boolean {
  return profile.env_override.includes(field)
}

export function keyStatus(profile: ModelProfileOut): '本机登录' | '已配置' | '未配置' {
  if (profile.api_key_env === null) return '本机登录'
  return profile.key_configured ? '已配置' : '未配置'
}
