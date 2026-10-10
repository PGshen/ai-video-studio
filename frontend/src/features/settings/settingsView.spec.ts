import { describe, expect, it } from 'vitest'
import type { ModelProfileOut, SettingsOut } from '@/types/api'
import {
  DEFAULT_PROFILE_STAGES,
  EXEC_SWITCH_RISKS,
  defaultProfileChoices,
  execSourceText,
  execSwitchVisible,
  isFieldLocked,
  keyStatus,
  webModeNotes,
  webModeSourceText,
} from './settingsView'

function profile(overrides: Partial<ModelProfileOut>): ModelProfileOut {
  return {
    id: 'p',
    name: 'p',
    provider: 'openai',
    model: 'm',
    runtime: 'openai',
    base_url: null,
    api_key_env: 'KEY',
    supports_vision: false,
    price_input: null,
    price_output: null,
    max_cost_per_turn: null,
    max_steps_per_turn: null,
    key_configured: true,
    builtin: false,
    env_override: [],
    ...overrides,
  }
}

function settings(overrides: Partial<SettingsOut> = {}): SettingsOut {
  return {
    stage_default_profile: {},
    web_mode: 'tools',
    web_mode_source: 'env',
    web_mode_env: 'tools',
    tts_default: { voice: 'zizi', speech_rate: 1 },
    default_style_preset_id: null,
    allow_unsandboxed_exec: false,
    allow_unsandboxed_exec_source: 'env',
    allow_unsandboxed_exec_env: false,
    sandbox_available: false,
    exec_mode: 'disabled',
    ...overrides,
  }
}

describe('DEFAULT_PROFILE_STAGES', () => {
  it('包含头脑风暴、各项目阶段（含创意与要求、配乐、配乐与动画和动画；Manim 的 animation 已下线）和风格对话，顺序与流水线一致（风格对话在最后）', () => {
    expect(DEFAULT_PROFILE_STAGES.map((s) => s.key)).toEqual([
      'brainstorm',
      'topic',
      'narrative',
      'concept',
      'music',
      'produce',
      'animation_html',
      'style',
    ])
  })
})

describe('defaultProfileChoices', () => {
  it('只列 key 已配置的配置', () => {
    const list = [
      profile({ id: 'a', name: 'a' }),
      profile({ id: 'b', name: 'b', key_configured: false }),
    ]
    expect(defaultProfileChoices(list, null).map((p) => p.id)).toEqual(['a'])
  })

  it('当前已选的配置即使 key 未配置也保留，避免选项凭空消失', () => {
    const list = [
      profile({ id: 'a', name: 'a' }),
      profile({ id: 'b', name: 'b', key_configured: false }),
    ]
    expect(defaultProfileChoices(list, 'b').map((p) => p.id)).toEqual(['a', 'b'])
  })

  it('当前已选的配置已被删除时不报错', () => {
    expect(defaultProfileChoices([profile({ id: 'a' })], 'gone').map((p) => p.id)).toEqual(['a'])
  })
})

describe('webModeSourceText', () => {
  it('界面覆盖时说明可以清除并回到环境变量的值', () => {
    const text = webModeSourceText(settings({ web_mode: 'native', web_mode_source: 'ui', web_mode_env: 'tools' }))
    expect(text).toContain('界面')
    expect(text).toContain('自建工具')
  })

  it('来自环境变量时说明来源', () => {
    expect(webModeSourceText(settings())).toContain('STUDIO_WEB_MODE')
  })
})

describe('webModeNotes', () => {
  it('tools 模式没有风险提示', () => {
    expect(webModeNotes('tools')).toEqual([])
  })

  it('native 模式说明没有 URL 来源保护，并标注 OpenAI 托管搜索经 OpenRouter 未验证（TD-39）', () => {
    const notes = webModeNotes('native').join('\n')
    expect(notes).toContain('URL')
    expect(notes).toContain('OpenAI')
    expect(notes).toContain('未验证')
  })
})

describe('isFieldLocked / keyStatus', () => {
  it('环境变量决定的字段被锁定', () => {
    const p = profile({ env_override: ['model', 'base_url'] })
    expect(isFieldLocked(p, 'model')).toBe(true)
    expect(isFieldLocked(p, 'price_input')).toBe(false)
  })

  it('key 状态：本机登录、已配置、未配置', () => {
    expect(keyStatus(profile({ api_key_env: null }))).toBe('本机登录')
    expect(keyStatus(profile({ api_key_env: 'K', key_configured: true }))).toBe('已配置')
    expect(keyStatus(profile({ api_key_env: 'K', key_configured: false }))).toBe('未配置')
  })
})

describe('无隔离执行开关（ADR 0024）', () => {
  it('只在本机没有沙箱时显示', () => {
    expect(execSwitchVisible(settings({ sandbox_available: false }))).toBe(true)
    expect(execSwitchVisible(settings({ sandbox_available: true, exec_mode: 'sandboxed' }))).toBe(
      false,
    )
  })

  it('风险说明提到能读本机文件、能联网，以及下一轮起生效', () => {
    const text = EXEC_SWITCH_RISKS.join('\n')
    expect(text).toContain('读')
    expect(text).toContain('联网')
    expect(text).toContain('下一轮')
  })

  it('来源文案：界面覆盖时说明可以清除并回到环境变量的值', () => {
    const text = execSourceText(
      settings({ allow_unsandboxed_exec_source: 'ui', allow_unsandboxed_exec_env: false }),
    )
    expect(text).toContain('界面')
    expect(text).toContain('关')
  })

  it('来源文案：来自环境变量时点名变量', () => {
    expect(execSourceText(settings())).toContain('STUDIO_ALLOW_UNSANDBOXED_EXEC')
  })
})
