import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CodeView from './CodeView.vue'

// 只关心文本与行数，不加载 shiki 语法高亮器。
vi.mock('@/components/ai-elements/code-block/utils', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ai-elements/code-block/utils')>()
  return { ...original, highlightCode: () => null }
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
})
