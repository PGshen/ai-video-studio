import { describe, expect, it } from 'vitest'
import { noticeText } from './noticeText'

describe('noticeText', () => {
  it('已知类型用中文标签，带 message 时用冒号接在后面', () => {
    expect(noticeText('guard_restored')).toBe('越界写入已被还原')
    expect(noticeText('guard_restored', '详情')).toBe('越界写入已被还原：详情')
  })

  it('换模型的提示自己就是完整的一句话，不再加标签', () => {
    expect(noticeText('model_switched', '模型已从 a 换为 b（m）')).toBe('模型已从 a 换为 b（m）')
  })

  it('换模型的提示没有 message 时用兜底文案', () => {
    expect(noticeText('model_switched')).toBe('模型已切换')
  })

  it('未知类型显示类型名', () => {
    expect(noticeText('mystery')).toBe('mystery')
    expect(noticeText('mystery', '说明')).toBe('mystery：说明')
  })
})
