import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { MusicRenderOut } from '@/types/api'
import RenderReport from './RenderReport.vue'

const OK: MusicRenderOut = {
  ok: true,
  errors: [],
  text: '配乐渲染成功',
  warnings: ['整体 RMS 偏高'],
  retime_note: '重定时校验通过',
  metrics: {
    peak_dbfs: -1,
    onsets: 12,
    event_matches: [{ name: 'kick', detectable: 4, matched: 4 }],
  },
  picture_base64: 'AAAA',
  picture_media_type: 'image/jpeg',
}

describe('RenderReport', () => {
  it('shows metrics, matches, warnings and the picture on success', () => {
    const wrapper = mount(RenderReport, { props: { report: OK } })
    expect(wrapper.text()).toContain('渲染成功')
    expect(wrapper.text()).toContain('-1.0 dBFS')
    expect(wrapper.find('[data-testid="render-matches"]').text()).toContain('kick 4/4')
    expect(wrapper.find('[data-testid="render-warnings"]').text()).toContain('RMS')
    expect(wrapper.find('[data-testid="render-picture"]').attributes('src')).toBe(
      'data:image/jpeg;base64,AAAA',
    )
  })

  it('lists the errors and says the old products are untouched on failure', () => {
    const wrapper = mount(RenderReport, {
      props: {
        report: { ...OK, ok: false, errors: ['脚本似乎写死了时间', '另一个'], picture_base64: null },
      },
    })
    expect(wrapper.text()).toContain('旧产物没有改动')
    expect(wrapper.findAll('[data-testid="render-errors"] li')).toHaveLength(2)
    expect(wrapper.find('[data-testid="render-picture"]').exists()).toBe(false)
  })
})
