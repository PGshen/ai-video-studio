import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { MessageResponse } from '@/components/ai-elements/message'
import { BLOCKED_COMPONENTS } from './blockedHtml'

// 第二层防御：即使源文本里的原始 HTML 漏过了转义，渲染层也把危险标签换成惰性占位。
async function render(content: string) {
  const wrapper = mount(MessageResponse, { props: { content }, attrs: { components: BLOCKED_COMPONENTS } })
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 100))
  await flushPromises()
  return wrapper
}
const tags = (w: Awaited<ReturnType<typeof render>>) =>
  [...w.element.querySelectorAll('*')].map((el) => el.tagName.toLowerCase())

describe('BLOCKED_COMPONENTS', () => {
  it.each([
    ['iframe', '<iframe src="https://evil.example"></iframe>'],
    ['meta', '<meta http-equiv="refresh" content="0;url=https://evil.example">'],
    ['form', '<form action="https://evil.example"><input name="x"></form>'],
    ['style', '<style>body{display:none}</style>'],
    ['img', '<img src="https://evil.example/x.png">'],
    ['object', '<object data="https://evil.example"></object>'],
    ['embed', '<embed src="https://evil.example">'],
    ['link', '<link rel="stylesheet" href="https://evil.example/x.css">'],
    ['base', '<base href="https://evil.example/">'],
  ])('原始 <%s> 不会变成真实元素', async (tag, html) => {
    const w = await render(`前\n\n${html}\n\n后`)

    expect(tags(w)).not.toContain(tag)
  })

  it('带 style 的容器标签（全屏覆盖层）被拦下，属性不会落到占位元素上', async () => {
    const w = await render('<div style="position:fixed;inset:0;background:#fff">overlay</div>')

    expect(w.html()).not.toContain('position:fixed')
    expect(tags(w)).not.toContain('div')
    expect(w.find('[data-blocked-html]').exists()).toBe(true)
  })

  it('占位元素丢弃传入的所有属性（src、href、style、on*）', async () => {
    const w = await render('<iframe src="https://evil.example" style="x:y" title="t"></iframe>')

    // 占位元素只有自己固定的 `data-blocked-html` 与 `class`，没有任何来自原始 HTML 的属性。
    const placeholder = w.get('[data-blocked-html]').element
    expect(placeholder.getAttributeNames().filter((n) => n !== 'data-blocked-html' && n !== 'class')).toEqual([])
    expect(placeholder.getAttribute('class')).toBe('text-muted-foreground')
  })

  it('正常的 Markdown（表格、代码、列表、加粗）不受影响', async () => {
    const w = await render('# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- 项一\n- 项二\n\n**粗** `code`\n\n```ts\nconst a = 1\n```')

    expect(tags(w)).toEqual(expect.arrayContaining(['table', 'li', 'code']))
    expect(w.find('[data-blocked-html]').exists()).toBe(false)
  })
})
