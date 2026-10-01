import { describe, expect, it } from 'vitest'
import { parseNumberedLines } from './readResult'

describe('parseNumberedLines', () => {
  it('解析 Claude Read 的 `行号→内容` 格式，返回起始行号和去掉前缀后的代码', () => {
    expect(parseNumberedLines('     1→# 风格\n     2→正文\n     3→')).toEqual({
      startLine: 1,
      code: '# 风格\n正文\n',
    })
  })

  it('带 offset 的结果起始行号不是 1', () => {
    expect(parseNumberedLines('    50→x = 1\n    51→y = 2')).toEqual({
      startLine: 50,
      code: 'x = 1\ny = 2',
    })
  })

  it('也接受 tab 分隔（cat -n）', () => {
    expect(parseNumberedLines('     1\tfoo\n     2\tbar')).toEqual({ startLine: 1, code: 'foo\nbar' })
  })

  it('内容里本身含箭头不会被误吃', () => {
    expect(parseNumberedLines('     1→a → b')?.code).toBe('a → b')
  })

  it('不是每行都带行号（自建 read_file、末尾有提示行等）时返回 null', () => {
    expect(parseNumberedLines('# 标题\n正文')).toBeNull()
    expect(parseNumberedLines('     1→a\n<system-reminder>注意</system-reminder>')).toBeNull()
    expect(parseNumberedLines('')).toBeNull()
  })

  it('行号不连续时返回 null（不是 Read 的输出）', () => {
    expect(parseNumberedLines('     1→a\n     5→b')).toBeNull()
  })
})
