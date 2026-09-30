import { describe, expect, it } from 'vitest'
import type { ModelProfileOut } from '@/types/api'
import {
  emptyProfileForm,
  formFromProfile,
  toCreateBody,
  toPatchBody,
  validateProfileForm,
  zeroBudgetWarning,
  type ProfileFormValues,
} from './profileForm'

function form(overrides: Partial<ProfileFormValues> = {}): ProfileFormValues {
  return {
    name: 'my-gpt',
    provider: 'openai',
    model: 'gpt-5-mini',
    runtime: 'openai',
    base_url: '',
    api_key_env: 'OPENAI_API_KEY',
    supports_vision: true,
    price_input: '0.25',
    price_output: '2',
    max_cost_per_turn: '0.5',
    max_steps_per_turn: '30',
    ...overrides,
  }
}

function profile(overrides: Partial<ModelProfileOut> = {}): ModelProfileOut {
  return {
    id: 'p1',
    name: 'gpt',
    provider: 'openai',
    model: 'gpt-5',
    runtime: 'openai',
    base_url: null,
    api_key_env: 'OPENAI_API_KEY',
    supports_vision: true,
    price_input: 1.25,
    price_output: 10,
    max_cost_per_turn: null,
    max_steps_per_turn: 30,
    key_configured: true,
    builtin: true,
    env_override: [],
    ...overrides,
  }
}

describe('validateProfileForm（与后端 db/repo/profiles.py 同一组规则）', () => {
  it('合法表单没有错误', () => {
    expect(validateProfileForm(form(), 'create')).toEqual({})
  })

  it('可选字段全部留空也合法', () => {
    const empty = form({
      base_url: '',
      price_input: '',
      price_output: '',
      max_cost_per_turn: '',
      max_steps_per_turn: '',
    })
    expect(validateProfileForm(empty, 'create')).toEqual({})
  })

  it.each([
    ['', '名称'],
    ['has space', '名称'],
    ['x'.repeat(51), '名称'],
    ['a/b', '名称'],
  ])('名称 %j 不合法', (name, needle) => {
    expect(validateProfileForm(form({ name }), 'create').name).toContain(needle)
  })

  it('名称允许中文、点、连字符和下划线', () => {
    expect(validateProfileForm(form({ name: '我的-模型_1.5' }), 'create').name).toBeUndefined()
  })

  it('provider、模型名不能为空', () => {
    const errors = validateProfileForm(form({ provider: ' ', model: '' }), 'create')
    expect(errors.provider).toBeDefined()
    expect(errors.model).toBeDefined()
  })

  it.each(['fake', 'gemini', ''])('运行时 %j 不合法', (runtime) => {
    expect(validateProfileForm(form({ runtime }), 'create').runtime).toBeDefined()
  })

  it.each(['ftp://example.com', 'not a url', 'example.com/v1'])('base_url %j 必须是 http(s)', (url) => {
    expect(validateProfileForm(form({ base_url: url }), 'create').base_url).toContain('http')
  })

  it('base_url 不能带账号密码', () => {
    expect(
      validateProfileForm(form({ base_url: 'https://user:secret@example.com/v1' }), 'create')
        .base_url,
    ).toContain('账号')
  })

  it('http/https 地址合法', () => {
    expect(
      validateProfileForm(form({ base_url: 'http://localhost:8080/v1' }), 'create').base_url,
    ).toBeUndefined()
  })

  it.each(['lower_case', '1BAD', 'sk-abcdefghijklmnop', 'HAS SPACE'])(
    'api_key_env %j 必须是环境变量名而不是 key',
    (value) => {
      expect(validateProfileForm(form({ api_key_env: value }), 'create').api_key_env).toContain(
        '环境变量',
      )
    },
  )

  it('只有 claude 运行时可以不填 api_key_env（本机登录）', () => {
    expect(
      validateProfileForm(form({ runtime: 'openai', api_key_env: '' }), 'create').api_key_env,
    ).toContain('本机登录')
    expect(
      validateProfileForm(form({ runtime: 'claude', api_key_env: '' }), 'create').api_key_env,
    ).toBeUndefined()
  })

  it.each(['-0.1', 'abc', 'Infinity', 'NaN'])('单价 %j 不合法', (value) => {
    const errors = validateProfileForm(form({ price_input: value, price_output: value }), 'create')
    expect(errors.price_input).toBeDefined()
    expect(errors.price_output).toBeDefined()
  })

  it('单轮成本上限不能为负，0 是合法的', () => {
    expect(validateProfileForm(form({ max_cost_per_turn: '-1' }), 'create').max_cost_per_turn).toBeDefined()
    expect(validateProfileForm(form({ max_cost_per_turn: '0' }), 'create').max_cost_per_turn).toBeUndefined()
  })

  it.each(['0', '-3', '1.5', 'abc'])('单轮步数上限 %j 必须是正整数', (value) => {
    expect(validateProfileForm(form({ max_steps_per_turn: value }), 'create').max_steps_per_turn).toBeDefined()
  })

  it('编辑时不检查 name/provider/runtime（它们不可改）', () => {
    const errors = validateProfileForm(form({ name: '', provider: '', runtime: 'fake' }), 'edit')
    expect(errors.name).toBeUndefined()
    expect(errors.provider).toBeUndefined()
    expect(errors.runtime).toBeUndefined()
  })

  it('fake 运行时的内置配置编辑时允许不填 api_key_env', () => {
    expect(
      validateProfileForm(form({ runtime: 'fake', api_key_env: '' }), 'edit').api_key_env,
    ).toBeUndefined()
  })
})

describe('toCreateBody', () => {
  it('把字符串输入转成数字，空字符串转 null，文本去首尾空白', () => {
    expect(
      toCreateBody(form({ name: ' my-gpt ', base_url: ' https://gw.example.com/v1 ', price_input: '0.25' })),
    ).toEqual({
      name: 'my-gpt',
      provider: 'openai',
      model: 'gpt-5-mini',
      runtime: 'openai',
      base_url: 'https://gw.example.com/v1',
      api_key_env: 'OPENAI_API_KEY',
      supports_vision: true,
      price_input: 0.25,
      price_output: 2,
      max_cost_per_turn: 0.5,
      max_steps_per_turn: 30,
    })
  })

  it('空的可选字段发 null', () => {
    const body = toCreateBody(
      form({ base_url: '', api_key_env: '', price_input: '', max_cost_per_turn: '', max_steps_per_turn: '' }),
    )
    expect(body.base_url).toBeNull()
    expect(body.api_key_env).toBeNull()
    expect(body.price_input).toBeNull()
    expect(body.max_cost_per_turn).toBeNull()
    expect(body.max_steps_per_turn).toBeNull()
  })
})

describe('formFromProfile / toPatchBody', () => {
  it('formFromProfile 把数字转成字符串、null 转空字符串', () => {
    const values = formFromProfile(profile({ base_url: null, max_cost_per_turn: null, api_key_env: null }))
    expect(values).toMatchObject({
      name: 'gpt',
      base_url: '',
      api_key_env: '',
      price_input: '1.25',
      max_cost_per_turn: '',
      max_steps_per_turn: '30',
    })
  })

  it('没改任何东西时补丁为空', () => {
    const original = profile()
    expect(toPatchBody(formFromProfile(original), original)).toEqual({})
  })

  it('只包含改过的字段，清空可空字段发 null', () => {
    const original = profile()
    const edited = { ...formFromProfile(original), model: 'gpt-5.1', max_steps_per_turn: '' }

    expect(toPatchBody(edited, original)).toEqual({ model: 'gpt-5.1', max_steps_per_turn: null })
  })

  it('不包含环境变量决定的字段，即使表单里被改了', () => {
    const original = profile({ env_override: ['model', 'base_url'] })
    const edited = { ...formFromProfile(original), model: 'x', base_url: 'https://x.example.com', max_steps_per_turn: '5' }

    expect(toPatchBody(edited, original)).toEqual({ max_steps_per_turn: 5 })
  })

  it('数值等价的写法不算改动（1.250 与 1.25）', () => {
    const original = profile()
    const edited = { ...formFromProfile(original), price_input: '1.250' }

    expect(toPatchBody(edited, original)).toEqual({})
  })
})

describe('emptyProfileForm', () => {
  it('新建默认是 openai 运行时、要填 key 环境变量', () => {
    const values = emptyProfileForm()
    expect(values.runtime).toBe('openai')
    expect(values.name).toBe('')
    expect(validateProfileForm(values, 'create').name).toBeDefined()
  })
})

describe('zeroBudgetWarning', () => {
  it('成本上限为 0 时提示每一轮都会被拒绝', () => {
    expect(zeroBudgetWarning(form({ max_cost_per_turn: '0' }))).toContain('每一轮')
  })

  it('其他情况没有提示', () => {
    expect(zeroBudgetWarning(form({ max_cost_per_turn: '0.5' }))).toBeNull()
    expect(zeroBudgetWarning(form({ max_cost_per_turn: '' }))).toBeNull()
  })
})
