import { VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { IdeaOut } from '@/types/api'
import IdeaCard from './IdeaCard.vue'

const idea: IdeaOut = {
  id: 'i1',
  title: '排序为什么快',
  pitch: '卖点',
  counterintuitive: null,
  tags: [],
  scores: {},
  status: 'idea',
  source_session_id: null,
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
}

function render(projectCount = 0) {
  return mount(IdeaCard, {
    props: { idea, projectCount },
    global: { plugins: [VueQueryPlugin] },
  })
}

describe('IdeaCard', () => {
  it('点卡片本身打开详情，没有单独的「详情」按钮', async () => {
    const w = render()

    expect(w.findAll('button').map((b) => b.text())).not.toContain('详情')
    await w.get('[data-testid="idea-card-i1"]').trigger('click')

    expect(w.emitted('detail')).toEqual([[idea]])
  })

  it('点底部的按钮只触发自己的操作，不打开详情', async () => {
    const w = render()

    await w.findAll('button').find((b) => b.text() === '创建项目')!.trigger('click')

    expect(w.emitted('create-project')).toEqual([[idea]])
    expect(w.emitted('detail')).toBeUndefined()
  })

  it('点删除按钮不打开详情', async () => {
    const w = render()

    await w.get('[data-testid="idea-delete-i1"]').trigger('click')

    expect(w.emitted('detail')).toBeUndefined()
  })

  it('卡片可以用键盘打开（Enter）', async () => {
    const w = render()

    await w.get('[data-testid="idea-card-i1"]').trigger('keydown', { key: 'Enter' })

    expect(w.emitted('detail')).toEqual([[idea]])
  })
})
