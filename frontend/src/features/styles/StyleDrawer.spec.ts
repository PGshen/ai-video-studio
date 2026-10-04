import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

// 抽屉的内容走 portal，这里把 Sheet 换成「open 时直接渲染」的桩，只测由 URL query 驱动的切换。
vi.mock('@/components/ui/sheet', () => {
  const pass = (name: string) => ({
    name,
    setup: (_p: unknown, { slots }: { slots: { default?: () => unknown } }) => () =>
      h('div', { 'data-sheet': name }, slots.default?.() as never),
  })
  return {
    Sheet: {
      props: ['open'],
      emits: ['update:open'],
      setup: (
        props: { open?: boolean },
        { slots, emit }: { slots: { default?: () => unknown }; emit: (e: 'update:open', v: boolean) => void },
      ) =>
        () =>
          // 真实的 Sheet 关闭动画结束后才卸载内容；桩里始终渲染，用 data-open 区分。
          h('div', { 'data-testid': 'sheet', 'data-open': String(props.open) }, [
            h('button', { 'data-testid': 'sheet-close', onClick: () => emit('update:open', false) }),
            slots.default?.() as never,
          ]),
    },
    SheetContent: pass('SheetContent'),
    SheetHeader: pass('SheetHeader'),
    SheetTitle: pass('SheetTitle'),
    SheetDescription: pass('SheetDescription'),
  }
})
vi.mock('./StyleDetailView.vue', () => ({
  default: {
    props: ['styleId'],
    emits: ['edit', 'close', 'open'],
    setup: (props: { styleId?: string }, { emit }: { emit: (e: string, ...a: unknown[]) => void }) => () =>
      h('div', { 'data-testid': 'detail-view', 'data-id': props.styleId }, [
        h('button', { 'data-testid': 'to-edit', onClick: () => emit('edit') }),
        h('button', { 'data-testid': 'detail-close', onClick: () => emit('close') }),
        h('button', { 'data-testid': 'open-other', onClick: () => emit('open', 'other') }),
      ]),
  },
}))
vi.mock('./StyleEditView.vue', () => ({
  default: {
    props: ['styleId'],
    emits: ['saved', 'discarded', 'close'],
    setup: (props: { styleId?: string }, { emit }: { emit: (e: string, ...a: unknown[]) => void }) => () =>
      h('div', { 'data-testid': 'edit-view', 'data-id': props.styleId }, [
        h('button', { 'data-testid': 'do-save', onClick: () => emit('saved', { id: props.styleId }) }),
        h('button', { 'data-testid': 'discard-old', onClick: () => emit('discarded', false) }),
        h('button', { 'data-testid': 'discard-new', onClick: () => emit('discarded', true) }),
        h('button', { 'data-testid': 'edit-close', onClick: () => emit('close') }),
      ]),
  },
}))

import StyleDrawer from './StyleDrawer.vue'

async function mountDrawer(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/styles', component: { template: '<div />' } }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(StyleDrawer, { global: { plugins: [router] } })
  return { wrapper, router }
}

const query = (router: ReturnType<typeof createRouter>) => router.currentRoute.value.query

describe('StyleDrawer 由 URL query 驱动', () => {
  it('没有 style 参数时是关闭的，也没有内容', async () => {
    const { wrapper } = await mountDrawer('/styles')
    expect(wrapper.get('[data-testid="sheet"]').attributes('data-open')).toBe('false')
    expect(wrapper.find('[data-testid="detail-view"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="edit-view"]').exists()).toBe(false)
  })

  it('有 style 参数时是打开的', async () => {
    const { wrapper } = await mountDrawer('/styles?style=a')
    expect(wrapper.get('[data-testid="sheet"]').attributes('data-open')).toBe('true')
  })

  it('mode=view（或缺省、或未知值）显示详情', async () => {
    for (const path of ['/styles?style=a&mode=view', '/styles?style=a', '/styles?style=a&mode=oops']) {
      const { wrapper } = await mountDrawer(path)
      expect(wrapper.get('[data-testid="detail-view"]').attributes('data-id')).toBe('a')
      expect(wrapper.find('[data-testid="edit-view"]').exists()).toBe(false)
    }
  })

  it('mode=edit 显示编辑', async () => {
    const { wrapper } = await mountDrawer('/styles?style=a&mode=edit')
    expect(wrapper.get('[data-testid="edit-view"]').attributes('data-id')).toBe('a')
    expect(wrapper.find('[data-testid="detail-view"]').exists()).toBe(false)
  })
})

describe('StyleDrawer 切换与关闭', () => {
  it('详情里点编辑 → mode=edit，且不新增历史记录', async () => {
    const { wrapper, router } = await mountDrawer('/styles?style=a&mode=view')

    await wrapper.get('[data-testid="to-edit"]').trigger('click')
    await vi.waitFor(() => expect(query(router)).toEqual({ style: 'a', mode: 'edit' }))
  })

  it('保存成功 → 回到 mode=view', async () => {
    const { wrapper, router } = await mountDrawer('/styles?style=a&mode=edit')

    await wrapper.get('[data-testid="do-save"]').trigger('click')
    await vi.waitFor(() => expect(query(router)).toEqual({ style: 'a', mode: 'view' }))
  })

  it('放弃已有风格的修改 → 回到 mode=view；放弃新建的 → 关闭抽屉', async () => {
    const first = await mountDrawer('/styles?style=a&mode=edit')
    await first.wrapper.get('[data-testid="discard-old"]').trigger('click')
    await vi.waitFor(() => expect(query(first.router)).toEqual({ style: 'a', mode: 'view' }))

    const second = await mountDrawer('/styles?style=n&mode=edit')
    await second.wrapper.get('[data-testid="discard-new"]').trigger('click')
    await vi.waitFor(() => expect(query(second.router)).toEqual({}))
  })

  it('复制后打开新的副本（view）', async () => {
    const { wrapper, router } = await mountDrawer('/styles?style=a&mode=view')

    await wrapper.get('[data-testid="open-other"]').trigger('click')
    await vi.waitFor(() => expect(query(router)).toEqual({ style: 'other', mode: 'view' }))
  })

  it('关闭（遮罩/×、详情或编辑里的关闭）只清掉 style 和 mode，保留别的参数', async () => {
    const a = await mountDrawer('/styles?style=a&mode=view&keep=1')
    await a.wrapper.get('[data-testid="sheet-close"]').trigger('click')
    await vi.waitFor(() => expect(query(a.router)).toEqual({ keep: '1' }))

    const b = await mountDrawer('/styles?style=a&mode=view')
    await b.wrapper.get('[data-testid="detail-close"]').trigger('click')
    await vi.waitFor(() => expect(query(b.router)).toEqual({}))

    const c = await mountDrawer('/styles?style=a&mode=edit')
    await c.wrapper.get('[data-testid="edit-close"]').trigger('click')
    await vi.waitFor(() => expect(query(c.router)).toEqual({}))
  })

  it('换了 style 参数时重建内容（不会带着上一套风格的编辑状态）', async () => {
    const { wrapper, router } = await mountDrawer('/styles?style=a&mode=edit')

    await router.push({ query: { style: 'b', mode: 'edit' } })

    expect(wrapper.get('[data-testid="edit-view"]').attributes('data-id')).toBe('b')
  })

  it('关闭后内容保留最后一次的样子，直到抽屉滑出（不会在动画期间变成空白）', async () => {
    const { wrapper, router } = await mountDrawer('/styles?style=a&mode=edit')

    await wrapper.get('[data-testid="sheet-close"]').trigger('click')
    await vi.waitFor(() => expect(query(router)).toEqual({}))

    expect(wrapper.get('[data-testid="sheet"]').attributes('data-open')).toBe('false')
    expect(wrapper.get('[data-testid="edit-view"]').attributes('data-id')).toBe('a')
  })
})
