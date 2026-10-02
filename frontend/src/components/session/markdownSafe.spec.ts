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

  describe('评审发现的绕过输入（转义器认为是代码、解析器不认为）', () => {
    const noRawTags = (text: string) => expect(escapeRawHtml(text)).not.toMatch(/<[a-z!/]/i)

    it('反斜杠转义的反引号不开启行内代码', () => {
      noRawTags('hi \\`<iframe src="https://evil.example"></iframe>\\` there')
    })

    it('信息串里带反引号的 ``` 不是围栏', () => {
      noRawTags('```a`\n<iframe src="x"></iframe>')
    })

    it('围栏长度不配对时，短的围栏行不会关闭长围栏（关不上就一直是代码，直到真正关闭）', () => {
      const text = '````\n```\n<b>\n````\n<i>x</i>'

      expect(escapeRawHtml(text)).toBe('````\n```\n<b>\n````\n&lt;i>x&lt;/i>')
    })

    it('关闭行带信息串（``` js）不算关闭', () => {
      expect(escapeRawHtml('```\n``` js\n<i>\n```\n<u>')).toBe('```\n``` js\n<i>\n```\n&lt;u>')
    })

    it('N 个反引号开头的代码段只被同样 N 个反引号关闭', () => {
      expect(escapeRawHtml('a ``x<b>`y`` z <i>')).toBe('a ``x<b>`y`` z &lt;i>')
    })

    it('没有配对的反引号不构成代码，其后的标签照常转义', () => {
      noRawTags('a ` <img src=x> b')
    })

    it('缩进超过 3 个空格的围栏不认（遇疑从严：宁可多转义，也不漏转义）', () => {
      noRawTags('- 列表\n\n     ```html\n     <iframe src="x"></iframe>\n     ```')
    })

    it('转义后的反斜杠加 < 也不留原始标签', () => {
      noRawTags('\\<iframe src="x">')
    })
  })
})
