import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { MusicMetaOut } from '@/types/api'
import AnalysisSummary from './AnalysisSummary.vue'

const BASE: MusicMetaOut = {
  form: 'import',
  rendered: true,
  stale: false,
  hash: 'h',
  duration: 20,
  bpm: null,
  events: [],
  sections: [],
  lyrics: [],
  lyrics_error: null,
  waveform: [],
  metrics: null,
  source: { filename: 'source.mp3', size: 3 * 1024 * 1024, sha256: 'h', duration: null },
  analysis: null,
  grid: null,
  range: null,
  energy: null,
}
const ANALYSIS = { bpm: 76.9, confidence: 0.84, residual_ms: 14, duration: 200.5, warnings: [] }
const mountSummary = (over: Partial<MusicMetaOut>) =>
  mount(AnalysisSummary, { props: { meta: { ...BASE, ...over } } })

describe('AnalysisSummary', () => {
  it('已上传未分析：显示源文件和“让 agent 分析”的空状态，没有摘要行与校验', () => {
    const wrapper = mountSummary({})
    expect(wrapper.find('[data-testid="music-source-info"]').text()).toContain('source.mp3 · 3.0 MB')
    expect(wrapper.find('[data-testid="music-analysis-empty"]').text()).toContain('analyze_music')
    expect(wrapper.findAll('[data-testid="music-analysis-row"]')).toHaveLength(0)
  })

  it('已分析：摘要行齐全，没有注意标记', () => {
    const wrapper = mountSummary({ analysis: ANALYSIS })
    expect(wrapper.findAll('[data-testid="music-analysis-row"]').map((r) => r.text())).toEqual([
      '76.9',
      '0.84',
      '14.0 ms',
      '3:20.5',
    ])
    expect(wrapper.findAll('[data-attention="true"]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="music-check"]').exists()).toBe(false)
  })

  it('低置信度与警告被标出来', () => {
    const wrapper = mountSummary({
      analysis: { ...ANALYSIS, confidence: 0.3, warnings: ['拍点不稳'] },
    })
    expect(wrapper.findAll('[data-attention="true"]').map((r) => r.text())).toEqual(['0.30', '拍点不稳'])
  })

  it('换歌后 stale：醒目提示，并且不再展示旧歌的分析摘要', () => {
    const wrapper = mountSummary({
      stale: true,
      analysis: ANALYSIS,
    })
    expect(wrapper.find('[data-testid="music-stale"]').text()).toContain('重新分析')
    expect(wrapper.findAll('[data-testid="music-analysis-row"]')).toHaveLength(0)
  })
})
