import { describe, expect, it } from 'vitest'
import type { ModelProfileOut } from '@/types/api'
import { preselectProfileId, switchBlockedReason, switchOptions } from './modelChoice'

function profile(overrides: Partial<ModelProfileOut>): ModelProfileOut {
  return {
    id: 'p',
    name: 'p',
    provider: 'anthropic',
    model: 'm',
    runtime: 'claude',
    base_url: null,
    api_key_env: null,
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

describe('switchOptions（与后端 switch_session_model_endpoint 同一组规则）', () => {
  const current = profile({ id: 'cur', name: 'login-a' })

  it('同 runtime、同 provider、同认证方式、key 已配置的可选；当前配置也在列表里且可选', () => {
    const options = switchOptions(current, [current, profile({ id: 'b', name: 'login-b' })])
    expect(options.map((o) => [o.profile.id, o.disabledReason])).toEqual([
      ['cur', null],
      ['b', null],
    ])
  })

  it('不同运行时被禁用并说明', () => {
    const options = switchOptions(current, [profile({ id: 'o', runtime: 'openai' })])
    expect(options[0]!.disabledReason).toContain('运行时')
  })

  it('不同供应商被禁用并说明', () => {
    const options = switchOptions(current, [profile({ id: 'o', provider: 'other' })])
    expect(options[0]!.disabledReason).toContain('供应商')
  })

  it('Claude 会话不能在本机登录和 API key 之间互换（未验证，TD-41）', () => {
    const options = switchOptions(current, [profile({ id: 'k', api_key_env: 'ANTHROPIC_API_KEY' })])
    expect(options[0]!.disabledReason).toContain('认证方式')
  })

  it('Claude 会话在同一个 API key 环境变量内可以互换', () => {
    const keyCurrent = profile({ id: 'k1', api_key_env: 'ANTHROPIC_API_KEY' })
    const options = switchOptions(keyCurrent, [
      profile({ id: 'k2', api_key_env: 'ANTHROPIC_API_KEY' }),
    ])
    expect(options[0]!.disabledReason).toBeNull()
  })

  it('非 Claude 运行时不受认证方式限制', () => {
    const openai = profile({
      id: 'a',
      runtime: 'openai',
      provider: 'openai',
      api_key_env: 'OPENAI_API_KEY',
    })
    const other = profile({
      id: 'b',
      runtime: 'openai',
      provider: 'openai',
      api_key_env: 'OPENROUTER_API_KEY',
    })
    expect(switchOptions(openai, [other])[0]!.disabledReason).toBeNull()
  })

  it('key 未配置被禁用并说明', () => {
    const options = switchOptions(current, [
      profile({ id: 'n', api_key_env: null, key_configured: false }),
    ])
    expect(options[0]!.disabledReason).toContain('密钥')
  })

  it('当前配置已不存在时所有选项都被禁用', () => {
    const options = switchOptions(undefined, [profile({ id: 'x' })])
    expect(options[0]!.disabledReason).toContain('不存在')
  })
})

describe('switchBlockedReason', () => {
  it('运行中不能换', () => {
    expect(switchBlockedReason('running')).toContain('运行')
  })

  it('空闲或中断的会话可以换', () => {
    expect(switchBlockedReason('idle')).toBeNull()
    expect(switchBlockedReason('interrupted')).toBeNull()
  })
})

describe('preselectProfileId（新建会话时预选哪个配置）', () => {
  const a = profile({ id: 'a', name: 'a' })
  const b = profile({ id: 'b', name: 'b' })
  const nokey = profile({ id: 'n', name: 'n', api_key_env: 'X', key_configured: false })

  it('该阶段有默认模型且仍可用时选它', () => {
    expect(preselectProfileId([a, b], { topic: 'b' }, 'topic')).toBe('b')
  })

  it('默认模型已被删除时回落到第一个已配置的', () => {
    expect(preselectProfileId([a, b], { topic: 'gone' }, 'topic')).toBe('a')
  })

  it('默认模型密钥未配置时回落到第一个已配置的', () => {
    expect(preselectProfileId([nokey, a], { topic: 'n' }, 'topic')).toBe('a')
  })

  it('没有默认模型时选第一个已配置的', () => {
    expect(preselectProfileId([nokey, a, b], {}, 'narrative')).toBe('a')
  })

  it('一个都没配置时选第一个（界面上会标注未配置），列表为空时返回空字符串', () => {
    expect(preselectProfileId([nokey], {}, 'topic')).toBe('n')
    expect(preselectProfileId([], {}, 'topic')).toBe('')
  })

  it('其他阶段的默认不影响当前阶段', () => {
    expect(preselectProfileId([a, b], { animation: 'b' }, 'topic')).toBe('a')
  })
})
