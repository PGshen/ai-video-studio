import { describe, expect, it } from 'vitest'
import {
  emptyVoiceForm,
  engineLabel,
  toVoiceCreate,
  validateVoiceForm,
  type VoiceFormValues,
} from './voiceForm'

function form(over: Partial<VoiceFormValues> = {}): VoiceFormValues {
  return {
    label: ' 新音色 ',
    alias: 'new_one',
    speaker_id: 'zh_female_new_uranus_bigtts',
    gender: 'male',
    engine: 'doubao_2.0',
    ...over,
  }
}

describe('validateVoiceForm', () => {
  it('accepts a valid form', () => {
    expect(validateVoiceForm(form())).toEqual({})
  })

  it('reports every problem at once', () => {
    const errors = validateVoiceForm(form({ label: ' ', alias: 'Bad Alias', speaker_id: '' }))
    expect(Object.keys(errors).sort()).toEqual(['alias', 'label', 'speaker_id'])
  })

  it.each(['', 'UPPER', 'has space', '中文', 'a'.repeat(41)])('rejects alias %j', (alias) => {
    expect(validateVoiceForm(form({ alias })).alias).toBeDefined()
  })

  it('rejects an alias that already exists', () => {
    expect(validateVoiceForm(form({ alias: 'zizi' }), [{ alias: 'zizi' }]).alias).toBe(
      '别名已被占用',
    )
  })

  it('rejects a speaker id with spaces', () => {
    expect(validateVoiceForm(form({ speaker_id: 'a b' })).speaker_id).toBeDefined()
  })
})

describe('toVoiceCreate', () => {
  it('trims the label and keeps the version', () => {
    expect(toVoiceCreate(form({ engine: 'doubao_1.0' }))).toEqual({
      alias: 'new_one',
      label: '新音色',
      gender: 'male',
      speaker_id: 'zh_female_new_uranus_bigtts',
      engine: 'doubao_1.0',
    })
  })
})

describe('engineLabel / emptyVoiceForm', () => {
  it('labels the two versions and falls back to the raw value', () => {
    expect(engineLabel('doubao_1.0')).toBe('豆包 v1')
    expect(engineLabel('doubao_2.0')).toBe('豆包 v2')
    expect(engineLabel('x')).toBe('x')
  })

  it('starts with v2 and a female voice', () => {
    expect(emptyVoiceForm()).toMatchObject({ engine: 'doubao_2.0', gender: 'female' })
  })
})
