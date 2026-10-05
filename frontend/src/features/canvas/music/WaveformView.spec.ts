import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WaveformView from './WaveformView.vue'

const props = {
  waveform: [0.2, 0.8, 0.5, 1],
  duration: 10,
  sections: [
    { id: 'a', label: 'BUILD', start: 0, end: 4 },
    { id: 'b', label: 'DROP', start: 4, end: 10 },
  ],
  events: [
    { name: 'kick', kind: 'onset', start: 1, end: 1.2 },
    { name: 'riser', kind: 'sweep', start: 5, end: 8 },
  ],
  currentTime: 5,
}

describe('WaveformView', () => {
  it('draws the sections, onsets, sweeps and the playhead', () => {
    const wrapper = mount(WaveformView, { props })
    expect(wrapper.findAll('[data-testid="waveform-section"]').map((s) => s.text())).toEqual([
      'BUILD',
      'DROP',
    ])
    expect(wrapper.findAll('[data-testid="waveform-onset"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="waveform-sweep"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="waveform-playhead"]').attributes('x1')).toBe('500')
  })

  it('emits the clicked time', async () => {
    const wrapper = mount(WaveformView, { props, attachTo: document.body })
    const svg = wrapper.find('svg').element
    svg.getBoundingClientRect = () => ({ left: 100, width: 400 }) as DOMRect
    await wrapper.find('svg').trigger('click', { clientX: 300 })
    expect(wrapper.emitted('seek')![0]).toEqual([5])
    wrapper.unmount()
  })

  it('ignores a click when the element has no size', async () => {
    const wrapper = mount(WaveformView, { props })
    await wrapper.find('svg').trigger('click', { clientX: 10 })
    expect(wrapper.emitted('seek')).toBeUndefined()
  })

  it('survives an empty waveform and a zero duration', () => {
    const wrapper = mount(WaveformView, {
      props: { ...props, waveform: [], duration: 0, sections: [], events: [] },
    })
    expect(wrapper.find('[data-testid="waveform-playhead"]').attributes('x1')).toBe('0')
  })
})
