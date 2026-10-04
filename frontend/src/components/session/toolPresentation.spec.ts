import { describe, expect, it } from 'vitest'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { describeTool, relativizePath, toolStatus } from './toolPresentation'

function call(name: string, args: Record<string, unknown>, result?: ToolCallItem['result']) {
  const item: ToolCallItem = { kind: 'tool_call', turnId: 't1', callId: 'c1', name, args }
  if (result) item.result = result
  return item
}
const ok = { text: 'ok', isError: false, truncated: false, images: [] }
const bad = { text: 'boom', isError: true, truncated: false, images: [] }

describe('relativizePath', () => {
  it('去掉给定的工作区前缀', () => {
    expect(relativizePath('/data/projects/p1/topic/a.md', '/data/projects/p1')).toBe('topic/a.md')
    expect(relativizePath('/data/projects/p1/topic/a.md', '/data/projects/p1/')).toBe('topic/a.md')
  })

  it('没有前缀时按 projects/<id>/ 与 scratch/<id>/ 推断', () => {
    expect(relativizePath('/Users/me/data/projects/abc/style/STYLE.md')).toBe('style/STYLE.md')
    expect(relativizePath('/Users/me/data/scratch/s1/notes.md')).toBe('notes.md')
    expect(relativizePath('/Users/me/data/style-drafts/s1/references/a.md')).toBe(
      'references/a.md',
    )
  })

  it('已经是相对路径或无法识别时原样返回', () => {
    expect(relativizePath('style/STYLE.md')).toBe('style/STYLE.md')
    expect(relativizePath('/etc/hosts')).toBe('/etc/hosts')
  })
})

describe('describeTool · 七类工具 × 两个运行时', () => {
  const cases: [string, Record<string, unknown>, string, string, string][] = [
    // [name, args, kind, label, summary]
    ['Read', { file_path: 'style/STYLE.md' }, 'read', '读取', 'style/STYLE.md'],
    ['read_file', { path: 'topic/notes/idea-card.md' }, 'read', '读取', 'topic/notes/idea-card.md'],
    ['Write', { file_path: 'topic/a.md', content: 'x' }, 'write', '写入', 'topic/a.md'],
    ['write_file', { path: 'topic/a.md', content: 'x' }, 'write', '写入', 'topic/a.md'],
    ['Edit', { file_path: 'topic/a.md', old_string: 'a', new_string: 'b' }, 'write', '编辑', 'topic/a.md'],
    ['MultiEdit', { file_path: 'topic/a.md', edits: [] }, 'write', '编辑', 'topic/a.md'],
    ['edit_file', { path: 'topic/a.md', old_text: 'a', new_text: 'b' }, 'write', '编辑', 'topic/a.md'],
    ['apply_patch', { type: 'create_file', path: 'topic/brief.md', diff: '+x' }, 'write', '补丁', 'topic/brief.md'],
    ['Glob', { pattern: '**/*.md' }, 'glob', 'Glob', '**/*.md'],
    ['list_files', { dir: 'topic' }, 'glob', '列目录', 'topic'],
    ['list_files', { dir: '' }, 'glob', '列目录', '工作区'],
    ['Grep', { pattern: 'TODO', path: 'topic' }, 'grep', 'Grep', 'TODO'],
    ['Bash', { command: 'ls -la', description: 'List files' }, 'bash', 'Bash', 'List files'],
    ['Bash', { command: 'ls topic/\ncat a.md' }, 'bash', 'Bash', 'ls topic/'],
    ['shell', { commands: ['ls', 'pwd'] }, 'bash', 'Bash', 'ls 等 2 条'],
    ['shell', { command: 'write topic/a.md' }, 'bash', 'Bash', 'write topic/a.md'],
    ['WebSearch', { query: 'btree 索引' }, 'web-search', '联网搜索', 'btree 索引'],
    ['web_search', { query: 'btree 索引', max_results: 5 }, 'web-search', '联网搜索', 'btree 索引'],
    ['WebFetch', { url: 'https://dev.mysql.com/doc/a.html', prompt: '总结' }, 'web-fetch', '读取网页', 'dev.mysql.com/doc/a.html'],
    ['fetch_url', { url: 'https://example.com/', max_chars: 6000 }, 'web-fetch', '读取网页', 'example.com'],
  ]

  it.each(cases)('%s %j → %s', (name, args, kind, label, summary) => {
    const view = describeTool(call(name, args))

    expect(view.kind).toBe(kind)
    expect(view.label).toBe(label)
    expect(view.summary).toBe(summary)
  })

  it('读写类工具带相对路径，并按工作区前缀去掉绝对前缀', () => {
    const view = describeTool(
      call('Write', { file_path: '/data/projects/p1/topic/a.md', content: '' }),
      '/data/projects/p1',
    )

    expect(view.path).toBe('topic/a.md')
    expect(view.summary).toBe('topic/a.md')
  })

  it('未知工具走 generic：工具名 + 第一个字符串参数（过长截断）', () => {
    const view = describeTool(call('create_idea', { count: 3, title: '冰箱门为什么难拉开' }))

    expect(view).toMatchObject({ kind: 'generic', label: 'create_idea', summary: '冰箱门为什么难拉开' })
    const long = describeTool(call('x', { s: 'a'.repeat(300) }))
    expect(long.summary.length).toBeLessThanOrEqual(81)
    expect(long.summary.endsWith('…')).toBe(true)
  })

  it('generic 没有字符串参数时摘要为空', () => {
    expect(describeTool(call('list_ideas', {})).summary).toBe('')
  })

  it('畸形参数退回 generic，摘要为工具名，不抛错', () => {
    for (const [name, args] of [
      ['Read', {}],
      ['Read', { file_path: 42 }],
      ['Bash', { command: ['ls'] }],
      ['shell', { commands: [] }],
      ['WebFetch', {}],
      ['web_search', {}],
      ['Grep', { pattern: null }],
      ['Glob', {}],
      ['apply_patch', {}],
    ] as [string, Record<string, unknown>][]) {
      const view = describeTool(call(name, args))
      expect(view.kind, `${name} ${JSON.stringify(args)}`).toBe('generic')
      expect(view.label).toBe(name)
    }
  })

  it('WebFetch 的 URL 不合法时摘要显示原文', () => {
    expect(describeTool(call('WebFetch', { url: 'not a url' })).summary).toBe('not a url')
  })
})

describe('toolStatus', () => {
  it('无结果且 turn 还在跑：running；已结束：interrupted', () => {
    expect(toolStatus(call('Read', {}), false)).toBe('running')
    expect(toolStatus(call('Read', {}), true)).toBe('interrupted')
  })

  it('有结果：done 或 error，和 turn 是否结束无关', () => {
    expect(toolStatus(call('Read', {}, ok), false)).toBe('done')
    expect(toolStatus(call('Read', {}, bad), true)).toBe('error')
  })
})
