import { describe, expect, it } from 'vitest'
import { fileNameProblem, groupFiles } from './styleFiles'

describe('groupFiles', () => {
  it('按入口、引用文件、金样本分组并保持顺序', () => {
    expect(
      groupFiles(['STYLE.md', 'exemplars/e1.json', 'references/a.md', 'references/b.md']),
    ).toEqual({
      hasEntry: true,
      references: ['references/a.md', 'references/b.md'],
      exemplars: ['exemplars/e1.json'],
    })
  })

  it('没有入口文件也能分组；不认识的路径不显示', () => {
    expect(groupFiles(['notes.md', 'other/x.md'])).toEqual({
      hasEntry: false,
      references: [],
      exemplars: [],
    })
  })
})

describe('fileNameProblem', () => {
  const none: string[] = []

  it.each([
    ['references', 'color.md'],
    ['references', '配色方案.md'],
    ['exemplars', 'e1.json'],
    ['exemplars', 'notes.md'],
    ['references', 'a-b_c.2.md'],
  ] as const)('%s/%s 合法', (directory, name) => {
    expect(fileNameProblem(directory, name, none)).toBeNull()
  })

  it('空名字', () => {
    expect(fileNameProblem('references', '  ', none)).toContain('不能为空')
  })

  it.each(['../evil.md', 'a/b.md', 'a b.md', 'a\\b.md', '.hidden.md'])('不允许的字符或开头：%s', (name) => {
    expect(fileNameProblem('references', name, none)).toContain('文件名')
  })

  it('太长', () => {
    expect(fileNameProblem('references', `${'x'.repeat(78)}.md`, none)).toContain('80')
  })

  it('扩展名：references 只能 .md，exemplars 只能 .json 或 .md', () => {
    expect(fileNameProblem('references', 'a.json', none)).toContain('.md')
    expect(fileNameProblem('exemplars', 'a.txt', none)).toContain('.json')
  })

  it('同目录重名', () => {
    expect(fileNameProblem('references', 'a.md', ['references/a.md'])).toContain('已有')
    expect(fileNameProblem('exemplars', 'a.md', ['references/a.md'])).toBeNull()
  })
})
