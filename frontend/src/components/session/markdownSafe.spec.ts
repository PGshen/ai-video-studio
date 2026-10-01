import { describe, expect, it } from 'vitest'
import { escapeRawHtml } from './markdownSafe'

describe('escapeRawHtml', () => {
  it('转义代码以外的 <，让原始 HTML 当文本显示', () => {
    expect(escapeRawHtml('<script>alert(1)</script>')).toBe('&lt;script>alert(1)&lt;/script>')
    expect(escapeRawHtml('<img src=x onerror=alert(1)>')).toBe('&lt;img src=x onerror=alert(1)>')
  })

  it('没有 < 的普通 Markdown 原样返回', () => {
    const text = '# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**粗体** [链接](https://a.example)'
    expect(escapeRawHtml(text)).toBe(text)
  })

  it('行内代码里的 < 保持原样（代码里转义会显示成 &lt;）', () => {
    expect(escapeRawHtml('用 `<div>` 标签，不要 <b>')).toBe('用 `<div>` 标签，不要 &lt;b>')
  })

  it('围栏代码块（``` 和 ~~~）里保持原样，块前后照常转义', () => {
    expect(escapeRawHtml('前 <i>\n```html\n<div>\n```\n后 <u>')).toBe(
      '前 &lt;i>\n```html\n<div>\n```\n后 &lt;u>',
    )
    expect(escapeRawHtml('~~~\n<p>\n~~~')).toBe('~~~\n<p>\n~~~')
  })

  it('流式输出里还没闭合的围栏按代码处理', () => {
    expect(escapeRawHtml('```html\n<scr')).toBe('```html\n<scr')
  })

  it('空串原样返回', () => {
    expect(escapeRawHtml('')).toBe('')
  })
})
