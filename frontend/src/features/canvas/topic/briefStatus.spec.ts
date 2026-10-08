import { describe, expect, it } from 'vitest'
import { BRIEF_PATH, computeBriefStatus, noteFiles } from './briefStatus'

describe('computeBriefStatus', () => {
  it('还没有检查结果时是 unknown', () => {
    expect(computeBriefStatus(undefined)).toMatchObject({ level: 'unknown', errors: [], warnings: [] })
  })

  it('检查请求失败且没有旧结果时是 failed，不再一直转圈', () => {
    const status = computeBriefStatus(undefined, true)
    expect(status.level).toBe('failed')
    expect(status.headline).toContain('检查失败')
    expect(status.errors).toEqual([])
  })

  it('请求失败但还有上一次的结果时，仍显示那份结果', () => {
    const status = computeBriefStatus({ ok: true, errors: [], warnings: [] }, true)
    expect(status.level).toBe('ok')
  })

  it('有错误：提示暂不满足定稿条件，并带上全部错误', () => {
    const status = computeBriefStatus({ ok: false, errors: ['缺少章节「风险点」', 'x'], warnings: ['w'] })
    expect(status.level).toBe('errors')
    expect(status.headline).toContain('不能定稿')
    expect(status.headline).toContain('2 个错误')
    expect(status.errors).toEqual(['缺少章节「风险点」', 'x'])
    expect(status.warnings).toEqual(['w'])
  })

  it('只有警告：可以定稿，但标出警告条数', () => {
    const status = computeBriefStatus({ ok: true, errors: [], warnings: ['a', 'b'] })
    expect(status.level).toBe('warnings')
    expect(status.headline).toContain('可以定稿')
    expect(status.headline).toContain('2 条警告')
  })

  it('全部通过', () => {
    const status = computeBriefStatus({ ok: true, errors: [], warnings: [] })
    expect(status.level).toBe('ok')
    expect(status.headline).toContain('可以定稿')
  })
})

describe('noteFiles', () => {
  it('只取 topic/notes/ 下的文本文件，去掉前缀作为标签，按路径排序', () => {
    const paths = [
      'topic/brief.md',
      'topic/notes/idea-card.md',
      'topic/notes/sorting.md',
      'topic/notes/sub/deep.txt',
      'topic/notes/diagram.png',
      'narrative/narrative.json',
      'upstream/topic/notes/x.md',
    ]
    expect(noteFiles(paths)).toEqual([
      { path: 'topic/notes/idea-card.md', label: 'idea-card.md' },
      { path: 'topic/notes/sorting.md', label: 'sorting.md' },
      { path: 'topic/notes/sub/deep.txt', label: 'sub/deep.txt' },
    ])
  })

  it('没有笔记时为空', () => {
    expect(noteFiles([BRIEF_PATH])).toEqual([])
  })
})
