import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { TopicCheckOut } from '@/types/api'
import BriefStatusIcon from './BriefStatusIcon.vue'

const mountIcon = (check: TopicCheckOut | undefined) =>
  mount(BriefStatusIcon, { props: { check }, attachTo: document.body })

describe('BriefStatusIcon', () => {
  it.each([
    [undefined, 'unknown', '正在检查简报…'],
    [{ ok: true, errors: [], warnings: [] }, 'ok', '可以定稿：简报结构检查通过'],
    [{ ok: true, errors: [], warnings: ['w1'] }, 'warnings', '可以定稿（有 1 条警告，不阻止定稿）'],
    [{ ok: false, errors: ['e1', 'e2'], warnings: [] }, 'errors', '不能定稿：简报有 2 个错误'],
  ] as const)('%j → 图标级别 %s，aria-label 是结论', (check, level, headline) => {
    const button = mountIcon(check as TopicCheckOut | undefined).get('[data-testid="brief-status"]')
    expect(button.attributes('data-level')).toBe(level)
    expect(button.attributes('aria-label')).toBe(headline)
  })

  it('检查失败：图标级别 failed，aria-label 说明失败，不转圈', () => {
    const w = mount(BriefStatusIcon, { props: { check: undefined, failed: true }, attachTo: document.body })
    const button = w.get('[data-testid="brief-status"]')
    expect(button.attributes('data-level')).toBe('failed')
    expect(button.attributes('aria-label')).toContain('检查失败')
    expect(w.find('.animate-spin').exists()).toBe(false)
  })

  it('键盘聚焦弹出气泡：结论 + 错误 + 警告', async () => {
    const w = mountIcon({ ok: false, errors: ['缺少标题'], warnings: ['来源偏少'] })
    await w.get('[data-testid="brief-status"]').trigger('focus')
    await new Promise((resolve) => setTimeout(resolve, 0))
    const tip = document.body.querySelector('[data-slot="tooltip-content"]')
    expect(tip?.textContent).toContain('不能定稿：简报有 1 个错误')
    expect(tip?.textContent).toContain('缺少标题')
    expect(tip?.textContent).toContain('警告：来源偏少')
  })

  it('检查还没返回时气泡只有一句话，不显示错误列表', async () => {
    const w = mountIcon(undefined)
    await w.get('[data-testid="brief-status"]').trigger('focus')
    await new Promise((resolve) => setTimeout(resolve, 0))
    const tip = document.body.querySelector('[data-slot="tooltip-content"]')
    expect(tip?.textContent).toContain('正在检查简报…')
    expect(tip?.querySelector('li')).toBeNull()
  })
})
