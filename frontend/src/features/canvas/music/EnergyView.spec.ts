import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EnergyView from './EnergyView.vue'

const props = {
  energy: { hop: 0.1, values: [0.2, 1, 0.5, 0.8] },
  grid: { bpm: 120, offset: 0.5, downbeats: [0.5, 2.5] },
  range: { start: 4.5, end: 18.5 },
  sections: [
    { id: 'a', label: 'intro', start: 0.5, end: 4.5 },
    { id: 'b', label: 'verse', start: 4.5, end: 12.5 },
  ],
  duration: 20,
  currentTime: 10,
}

describe('EnergyView', () => {
  it('画段落名、强拍线（粗）、拍线（细）、区间外遮罩和播放位置', () => {
    const wrapper = mount(EnergyView, { props })
    expect(wrapper.findAll('[data-testid="energy-section"]').map((s) => s.text())).toEqual([
      'intro',
      'verse',
    ])
    expect(wrapper.findAll('[data-testid="energy-downbeat"]').length).toBeGreaterThan(0)
    expect(wrapper.findAll('[data-testid="energy-beat"]').length).toBeGreaterThan(0)
    expect(wrapper.find('[data-testid="energy-mask-left"]').attributes('width')).toBe('225')
    expect(wrapper.find('[data-testid="energy-mask-right"]').attributes('x')).toBe('925')
    expect(wrapper.find('[data-testid="energy-playhead"]').attributes('x1')).toBe('500')
  })

  it('区间内才有拍线：区间外的拍线不画', () => {
    const wrapper = mount(EnergyView, { props })
    const xs = [
      ...wrapper.findAll('[data-testid="energy-downbeat"]'),
      ...wrapper.findAll('[data-testid="energy-beat"]'),
    ].map((l) => Number(l.attributes('x1')))
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(225)
    expect(Math.max(...xs)).toBeLessThanOrEqual(925)
  })

  it('没有区间时没有遮罩；没有网格时没有拍线', () => {
    const wrapper = mount(EnergyView, { props: { ...props, range: null, grid: null } })
    expect(wrapper.find('[data-testid="energy-mask-left"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="energy-downbeat"]')).toHaveLength(0)
  })

  it('点击曲线发出整曲时间；点击段落名跳到段落起点', async () => {
    const wrapper = mount(EnergyView, { props, attachTo: document.body })
    const svg = wrapper.find('svg')
    svg.element.getBoundingClientRect = () => ({ left: 100, width: 400 }) as DOMRect
    await svg.trigger('click', { clientX: 300 })
    expect(wrapper.emitted('seek')![0]).toEqual([10])
    await wrapper.findAll('[data-testid="energy-section"]')[1]!.trigger('click')
    expect(wrapper.emitted('seek')![1]).toEqual([4.5])
    wrapper.unmount()
  })

  it('元素没有尺寸时忽略点击', async () => {
    const wrapper = mount(EnergyView, { props, attachTo: document.body })
    wrapper.find('svg').element.getBoundingClientRect = () => ({ left: 0, width: 0 }) as DOMRect
    await wrapper.find('svg').trigger('click', { clientX: 10 })
    expect(wrapper.emitted('seek')).toBeUndefined()
    wrapper.unmount()
  })
})
