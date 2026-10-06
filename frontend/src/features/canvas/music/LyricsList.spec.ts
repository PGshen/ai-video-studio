import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LyricsList from './LyricsList.vue'

const LINES = [
  { text: '第一句', start: 2, end: 6 },
  { text: '第二句', start: 6, end: 10 },
  { text: '第三句', start: 70, end: 75 },
]
const mountList = (currentTime = 0) => mount(LyricsList, { props: { lines: LINES, currentTime } })

describe('LyricsList', () => {
  it('每句一行：时间（分:秒）加文字', () => {
    const rows = mountList().findAll('[data-testid="lyric-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.text()).toContain('0:02')
    expect(rows[0]!.text()).toContain('第一句')
    expect(rows[2]!.text()).toContain('1:10')
  })

  it('当前行跟随播放位置高亮（aria-current），之前没有高亮', () => {
    const before = mountList(1).findAll('[data-testid="lyric-row"]')
    expect(before.some((r) => r.attributes('aria-current') === 'true')).toBe(false)
    const during = mountList(7).findAll('[data-testid="lyric-row"]')
    expect(during.map((r) => r.attributes('aria-current'))).toEqual([undefined, 'true', undefined])
  })

  it('点击一行发出 seek，参数是这句的开始秒', async () => {
    const wrapper = mountList()
    await wrapper.findAll('[data-testid="lyric-row"]')[2]!.trigger('click')
    expect(wrapper.emitted('seek')).toEqual([[70]])
  })

  it('没有歌词时什么都不画', () => {
    const wrapper = mount(LyricsList, { props: { lines: [], currentTime: 0 } })
    expect(wrapper.find('[data-testid="lyrics-list"]').exists()).toBe(false)
  })
})
