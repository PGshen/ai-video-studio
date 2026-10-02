import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CodeView from './CodeView.vue'

// 只关心文本与行数，不加载 shiki 语法高亮器。
vi.mock('@/components/ai-elements/code-block/utils', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ai-elements/code-block/utils')>()
  return {
    ...original,
    highlightCode: (code: string) =>
      code.startsWith('# ')
        ? {
            fg: 'inherit',
            bg: 'transparent',
            tokens: [
              [{ content: code, htmlStyle: { color: '#005CC5', '--shiki-light-font-weight': 'bold' } }],
            ],
          }
        : null,
  }
})

const lines = (code: string) =>
  mount(CodeView, { props: { code, language: 'text', lineNumbers: true } }).findAll('code > span')

describe('CodeView', () => {
  it('每行一个元素', () => {
    expect(lines('a\nb')).toHaveLength(2)
  })

  it('内容以换行结尾时不多出一个空行（否则行号会多一行）', () => {
    expect(lines('a\nb\n')).toHaveLength(2)
  })

  it('中间的空行保留，只去掉末尾那一个换行', () => {
    expect(lines('a\n\nb\n')).toHaveLength(3)
  })

  it('字号比默认的小一档，适合放在工具面板里', () => {
    const pre = mount(CodeView, { props: { code: 'a', language: 'text' } }).get('pre')
    expect(pre.element.closest('[data-testid="code-view"]')?.classList).toContain('[&_pre]:text-xs!')
  })

  it('shiki 主题里的粗体和下划线在浅色主题下也生效', () => {
    const wrapper = mount(CodeView, { props: { code: '# T', language: 'markdown' } })
    expect(wrapper.get('code span span').classes()).toEqual(
      expect.arrayContaining(['[font-weight:var(--shiki-light-font-weight)]']),
    )
  })
})
