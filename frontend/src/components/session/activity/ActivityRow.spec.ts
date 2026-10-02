import { mount } from '@vue/test-utils'
import { FileTextIcon } from '@lucide/vue'
import { describe, expect, it } from 'vitest'
import ActivityRow from './ActivityRow.vue'

const mountRow = (props: { open?: boolean; status?: 'running' | 'done' } = {}) =>
  mount(ActivityRow, {
    props: { icon: FileTextIcon, label: '读取', summary: 'a.md', status: 'done', open: false, ...props },
    slots: { default: '<p>body</p>' },
  })

describe('ActivityRow', () => {
  it('图标和折叠箭头在同一个前导位置，行尾没有箭头', () => {
    const wrapper = mountRow()
    const lead = wrapper.get('[data-testid="row-lead"]')
    expect(lead.findAll('svg')).toHaveLength(2)
    expect(wrapper.findAll('svg')).toHaveLength(2)
  })

  it('箭头平时隐藏，悬停整行或展开时才显示，同时图标让位', () => {
    const [icon, chevron] = mountRow().get('[data-testid="row-lead"]').findAll('svg')
    expect(icon.classes()).toEqual(
      expect.arrayContaining(['group-hover/trigger:hidden', 'group-data-[state=open]/trigger:hidden']),
    )
    expect(chevron.classes()).toEqual(
      expect.arrayContaining(['hidden', 'group-hover/trigger:block', 'group-data-[state=open]/trigger:block']),
    )
  })

  it('运行中的转圈仍在行尾', () => {
    const wrapper = mountRow({ status: 'running' })
    expect(wrapper.findAll('svg')).toHaveLength(3)
    expect(wrapper.get('[data-testid="row-lead"]').findAll('svg')).toHaveLength(2)
  })
})
