import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { StyleSummaryOut } from '@/types/api'

const state = vi.hoisted(() => ({
  styles: [] as unknown[],
  pending: false,
  error: false,
  createStyle: vi.fn(),
}))

vi.mock('@/composables/queries', () => ({
  useStylesQuery: () => ({
    data: ref(state.styles),
    isPending: ref(state.pending),
    isError: ref(state.error),
  }),
  useCreateStyleMutation: () => ({ mutateAsync: state.createStyle, isPending: ref(false) }),
}))

import StyleGrid from './StyleGrid.vue'

function style(id: string, overrides: Partial<StyleSummaryOut> = {}): StyleSummaryOut {
  return {
    id,
    name: `风格 ${id}`,
    category: '概念传记',
    description: `${id} 的简介`,
    reference_count: 3,
    exemplar_count: 1,
    is_default: false,
    has_draft: false,
    modified_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

async function mountGrid(path = '/styles') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/styles', component: { template: '<div />' } }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(StyleGrid, { global: { plugins: [router] } })
  return { wrapper, router }
}

const cardIds = (w: ReturnType<typeof mount>) =>
  w.findAll('[data-testid^="style-card-"]').map((c) => c.attributes('data-testid')!.slice(11))

beforeEach(() => {
  state.styles = []
  state.pending = false
  state.error = false
  state.createStyle.mockReset()
})

describe('StyleGrid 状态提示', () => {
  it('加载中、加载失败、风格库为空各有提示', async () => {
    state.pending = true
    expect((await mountGrid()).wrapper.text()).toContain('加载中')

    state.pending = false
    state.error = true
    expect((await mountGrid()).wrapper.text()).toContain('风格库加载失败')

    state.error = false
    expect((await mountGrid()).wrapper.get('[data-testid="style-empty"]').text()).toContain(
      '风格库还是空的',
    )
  })

  it('筛选后没有结果时提示，并且和空库区分开', async () => {
    state.styles = [style('a')]
    const { wrapper } = await mountGrid()

    await wrapper.get('[data-testid="style-search"]').setValue('不存在的关键词')

    expect(wrapper.get('[data-testid="style-empty"]').text()).toContain('没有符合筛选条件的风格')
  })
})

describe('StyleGrid 筛选与排序', () => {
  it('默认风格排在前面，其余按最近修改倒序', async () => {
    state.styles = [
      style('old', { modified_at: '2026-09-01T00:00:00Z' }),
      style('new', { modified_at: '2026-10-03T00:00:00Z' }),
      style('def', { is_default: true, modified_at: '2026-08-01T00:00:00Z' }),
    ]
    const { wrapper } = await mountGrid()
    expect(cardIds(wrapper)).toEqual(['def', 'new', 'old'])
  })

  it('关键词筛选名称和简介', async () => {
    state.styles = [style('a'), style('b', { name: '冷白学术图解' })]
    const { wrapper } = await mountGrid()

    await wrapper.get('[data-testid="style-search"]').setValue('冷白')

    expect(cardIds(wrapper)).toEqual(['b'])
  })

  it('点分类标记筛选，再点一次取消', async () => {
    state.styles = [style('a', { category: '科普' }), style('b', { category: '概念传记' })]
    const { wrapper } = await mountGrid()

    await wrapper.get('[data-testid="style-category-科普"]').trigger('click')
    expect(cardIds(wrapper)).toEqual(['a'])
    await wrapper.get('[data-testid="style-category-科普"]').trigger('click')
    expect(cardIds(wrapper).sort()).toEqual(['a', 'b'])
  })

  it('「仅看默认」', async () => {
    state.styles = [style('a'), style('b', { is_default: true })]
    const { wrapper } = await mountGrid()

    await wrapper.get('[data-testid="style-only-default"]').trigger('click')

    expect(cardIds(wrapper)).toEqual(['b'])
  })
})

describe('StyleGrid 分页', () => {
  const many = () =>
    Array.from({ length: 13 }, (_, i) =>
      style(`s${String(i).padStart(2, '0')}`, {
        modified_at: `2026-10-${String(13 - i).padStart(2, '0')}T00:00:00Z`,
      }),
    )

  it('一页 12 张，翻页后显示剩下的', async () => {
    state.styles = many()
    const { wrapper } = await mountGrid()
    expect(cardIds(wrapper)).toHaveLength(12)

    await wrapper
      .get('[data-testid="list-pagination"]')
      .findAll('button')
      .find((b) => b.text() === '下一页')!
      .trigger('click')

    expect(cardIds(wrapper)).toEqual(['s12'])
  })

  it('筛选条件变化后回到第 1 页', async () => {
    state.styles = many()
    const { wrapper } = await mountGrid()
    await wrapper
      .get('[data-testid="list-pagination"]')
      .findAll('button')
      .find((b) => b.text() === '下一页')!
      .trigger('click')

    await wrapper.get('[data-testid="style-search"]').setValue('s0')

    expect(cardIds(wrapper)).toHaveLength(10)
    expect(wrapper.find('[data-testid="list-pagination"]').exists()).toBe(false)
  })
})

describe('StyleGrid 打开抽屉（只改 URL query）', () => {
  it('点卡片 → mode=view', async () => {
    state.styles = [style('a')]
    const { wrapper, router } = await mountGrid()

    await wrapper.get('[data-testid="style-card-a"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ style: 'a', mode: 'view' })
  })

  it('点编辑按钮 → mode=edit', async () => {
    state.styles = [style('a')]
    const { wrapper, router } = await mountGrid()

    await wrapper.get('[data-testid="style-edit-a"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ style: 'a', mode: 'edit' })
  })
})

describe('StyleGrid 新建风格', () => {
  it('创建草稿后直接以编辑态打开新风格', async () => {
    state.createStyle.mockResolvedValue({ id: 'new1', is_new: true, dirty: true, files: ['STYLE.md'] })
    const { wrapper, router } = await mountGrid()

    await wrapper.get('[data-testid="new-style"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ style: 'new1', mode: 'edit' })
  })

  it('创建失败时显示原因，不跳转', async () => {
    state.createStyle.mockRejectedValue(new Error('磁盘已满'))
    const { wrapper, router } = await mountGrid()

    await wrapper.get('[data-testid="new-style"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="style-action-error"]').text()).toContain('磁盘已满')
    expect(router.currentRoute.value.query).toEqual({})
  })
})
