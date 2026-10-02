import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { ToolCallItem } from '@/composables/useSessionStream'
import { describeTool, toolStatus } from '@/components/session/toolPresentation'
import ToolBody from '@/components/session/activity/ToolBody.vue'

// shiki 的高亮是异步的，先显示原始文本；测试只关心文本和结构，不加载语法高亮器。
vi.mock('@/components/ai-elements/code-block/utils', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ai-elements/code-block/utils')>()
  return { ...original, highlightCode: () => null }
})

type Result = NonNullable<ToolCallItem['result']>
const res = (text: string, extra: Partial<Result> = {}): Result => ({
  text,
  isError: false,
  truncated: false,
  images: [],
  ...extra,
})
const err = (text: string): Result => res(text, { isError: true })

function render(name: string, args: Record<string, unknown>, result?: Result, turnEnded = true) {
  const item: ToolCallItem = {
    kind: 'tool_call',
    turnId: 't1',
    callId: 'c1',
    name,
    args,
    ...(result ? { result } : {}),
  }
  return mount(ToolBody, {
    props: { item, view: describeTool(item), status: toolStatus(item, turnEnded), projectId: null },
  })
}
const title = (w: ReturnType<typeof render>) => w.find('[data-testid="tool-pane"] [data-testid="tool-pane-title"]')

describe('Read', () => {
  it('Claude Read：去掉行号前缀，标题栏是路径，语言按扩展名', async () => {
    const w = render('Read', { file_path: 'style/STYLE.md' }, res('     1→# 风格\n     2→正文'))
    await flushPromises()

    expect(title(w).text()).toBe('style/STYLE.md')
    expect(w.text()).toContain('markdown')
    expect(w.text()).toContain('# 风格')
    expect(w.text()).not.toContain('1→')
  })

  it('自建 read_file：没有行号的结果也能显示', async () => {
    const w = render('read_file', { path: 'topic/notes/idea-card.md' }, res('# 卡片\n内容'))
    await flushPromises()

    expect(title(w).text()).toBe('topic/notes/idea-card.md')
    expect(w.text()).toContain('内容')
  })

  it('带 offset 的结果保留原始行号，并显示 offset/limit', async () => {
    const w = render('Read', { file_path: 'a.py', offset: 50, limit: 2 }, res('    50→x = 1\n    51→y = 2'))
    await flushPromises()

    expect(w.text()).toContain('50→x = 1')
    expect(w.text()).toContain('offset 50')
    expect(w.text()).toContain('limit 2')
  })

  it('被截断时提示已截断；出错时显示错误面板；没有结果时显示等待', () => {
    expect(render('Read', { file_path: 'a.md' }, res('x', { truncated: true })).text()).toContain('已截断')
    const failed = render('Read', { file_path: 'a.md' }, err('文件不存在'))
    expect(failed.text()).toContain('文件不存在')
    expect(failed.find('[data-testid="tool-pane-error"]').exists()).toBe(true)
    expect(render('Read', { file_path: 'a.md' }, undefined, false).text()).toContain('读取中')
  })

  it('空结果显示（无输出）', () => {
    expect(render('Read', { file_path: 'a.md' }, res('')).text()).toContain('（无输出）')
  })
})

describe('Write / Edit / apply_patch', () => {
  it('Write 与 write_file：显示写入的内容，结果是一行状态', async () => {
    for (const [name, args] of [
      ['Write', { file_path: 'topic/a.md', content: '# 标题\n正文' }],
      ['write_file', { path: 'topic/a.md', content: '# 标题\n正文' }],
    ] as [string, Record<string, unknown>][]) {
      const w = render(name, args, res('已写入 topic/a.md'))
      await flushPromises()

      expect(title(w).text()).toBe('topic/a.md')
      expect(w.text()).toContain('# 标题')
      expect(w.text()).toContain('已写入 topic/a.md')
    }
  })

  it('Edit 与 edit_file：旧文本整体标删除、新文本整体标新增', () => {
    for (const [name, args] of [
      ['Edit', { file_path: 'a.md', old_string: '旧一\n旧二', new_string: '新' }],
      ['edit_file', { path: 'a.md', old_text: '旧一\n旧二', new_text: '新' }],
    ] as [string, Record<string, unknown>][]) {
      const w = render(name, args, res('ok'))

      expect(w.findAll('[data-diff="del"]').map((l) => l.text())).toEqual(['-旧一', '-旧二'])
      expect(w.findAll('[data-diff="add"]').map((l) => l.text())).toEqual(['+新'])
    }
  })

  it('MultiEdit：每处修改一段差异', () => {
    const w = render(
      'MultiEdit',
      { file_path: 'a.md', edits: [{ old_string: 'a', new_string: 'b' }, { old_string: 'c', new_string: 'd' }] },
      res('ok'),
    )

    expect(w.findAll('[data-diff="del"]')).toHaveLength(2)
    expect(w.findAll('[data-diff="add"]')).toHaveLength(2)
  })

  it('apply_patch：按行首字符着色，@@ 行是 hunk', () => {
    const w = render(
      'apply_patch',
      { type: 'update_file', path: 'topic/brief.md', diff: '@@\n 不变\n-旧\n+新' },
      res('Done'),
    )

    expect(w.findAll('[data-diff="hunk"]').map((l) => l.text())).toEqual(['@@'])
    expect(w.findAll('[data-diff="del"]').map((l) => l.text())).toEqual(['-旧'])
    expect(w.findAll('[data-diff="add"]').map((l) => l.text())).toEqual(['+新'])
    expect(w.findAll('[data-diff="ctx"]').map((l) => l.text())).toEqual(['不变'])
  })

  it('apply_patch 的 create_file：全部是新增行', () => {
    const w = render('apply_patch', { type: 'create_file', path: 'a.md', diff: '+# 标题\n+正文' }, res('ok'))

    expect(w.findAll('[data-diff="add"]')).toHaveLength(2)
  })

  it('缺少内容参数时退回通用正文（参数 JSON），不抛错', () => {
    const w = render('Write', { file_path: 'a.md' }, res('ok'))

    expect(w.text()).toContain('参数')
    expect(w.text()).toContain('file_path')
  })

  it('参数缺失退回通用正文且写入失败：错误只出现一次', () => {
    const w = render('Write', { file_path: 'a.md' }, err('不在可写范围内：a.md'))

    expect(w.text().match(/不在可写范围内/g)).toHaveLength(1)
  })

  it('写入失败：显示错误面板', () => {
    const w = render('Write', { file_path: 'a.md', content: 'x' }, err('不在可写范围内：a.md'))

    expect(w.find('[data-testid="tool-pane-error"]').text()).toContain('不在可写范围内')
  })
})

describe('Glob / list_files / Grep', () => {
  it('Glob：结果逐行成列表，工作区绝对前缀被去掉', () => {
    const w = render(
      'Glob',
      { pattern: '**/*.md' },
      res('topic/a.md\n/Users/me/data/projects/p1/style/STYLE.md'),
    )

    expect(w.findAll('[data-testid="glob-entry"]').map((l) => l.text())).toEqual([
      'topic/a.md',
      'style/STYLE.md',
    ])
  })

  it('list_files 同样；无匹配显示（无匹配）', () => {
    const listed = render('list_files', { dir: '' }, res('topic/a.md\ntopic/b.md'))
    expect(listed.findAll('[data-testid="glob-entry"]')).toHaveLength(2)
    expect(render('Glob', { pattern: '*.zzz' }, res('')).text()).toContain('（无匹配）')
  })

  it('Grep：保留换行的等宽文本，并显示搜索范围', () => {
    const w = render(
      'Grep',
      { pattern: 'TODO', path: 'topic', glob: '*.md' },
      res('topic/a.md:3:TODO fix\ntopic/b.md:9:TODO later'),
    )

    expect(w.text()).toContain('TODO fix')
    expect(w.text()).toContain('TODO later')
    expect(w.text()).toContain('topic')
    expect(w.text()).toContain('*.md')
  })
})

describe('Bash / shell', () => {
  it('Bash：命令行带 $，输出在下方，状态点是完成', () => {
    const w = render('Bash', { command: 'ls -la', description: 'List files' }, res('total 0'))

    expect(w.text()).toContain('$ ls -la')
    expect(w.text()).toContain('total 0')
    expect(w.get('[data-testid="bash-status"]').attributes('data-status')).toBe('done')
  })

  it('shell 的 commands 逐条列出', () => {
    const w = render('shell', { commands: ['ls', 'pwd'] }, res('x'))

    expect(w.findAll('[data-testid="bash-command"]').map((l) => l.text())).toEqual(['$ ls', '$ pwd'])
  })

  it('运行中状态点是 running；失败时输出仍显示且状态点是 error（不重复错误面板）', () => {
    const running = render('Bash', { command: 'sleep 9' }, undefined, false)
    expect(running.get('[data-testid="bash-status"]').attributes('data-status')).toBe('running')

    const failed = render('Bash', { command: 'false' }, err('exit 1'))
    expect(failed.get('[data-testid="bash-status"]').attributes('data-status')).toBe('error')
    expect(failed.text()).toContain('exit 1')
    expect(failed.find('[data-testid="tool-pane-error"]').exists()).toBe(false)
  })

  it('复制内容是命令加输出', () => {
    const w = render('Bash', { command: 'echo hi' }, res('hi'))

    expect(w.get('[data-testid="tool-pane-copy"]').exists()).toBe(true)
  })

  it('命令只有 command 字段（FakeRuntime 的 shell）也能显示', () => {
    expect(render('shell', { command: 'write topic/a.md' }, res('ok')).text()).toContain(
      '$ write topic/a.md',
    )
  })
})

const customSearch = `搜索「b+ tree」，共 2 条结果：
1. B+ Tree vs Hash Index | SQLpipe
   https://www.sqlpipe.com/blog/b-tree-vs-hash-index
   摘要一
2. Indexing Explained
   https://example.com/indexing
   发布时间：Sat, 25 Jul 2026 16:00:00 GMT
   摘要二`
const nativeSearch = `Web search results for query: "q"\n\nLinks: [{"title":"Overview","url":"https://severalnines.com/blog/x/"}]`

describe('WebSearch / web_search', () => {
  it('自建格式：每条结果一张卡片（标题链接、域名、发布时间、摘要）', () => {
    const w = render('web_search', { query: 'b+ tree' }, res(customSearch))

    const hits = w.findAll('[data-testid="search-hit"]')
    expect(hits).toHaveLength(2)
    expect(hits[0]!.get('a').attributes('href')).toBe('https://www.sqlpipe.com/blog/b-tree-vs-hash-index')
    expect(hits[0]!.text()).toContain('www.sqlpipe.com')
    expect(hits[0]!.text()).toContain('摘要一')
    expect(hits[1]!.text()).toContain('Sat, 25 Jul 2026')
  })

  it('Claude 原生 Links JSON', () => {
    const w = render('WebSearch', { query: 'q' }, res(nativeSearch))

    expect(w.findAll('[data-testid="search-hit"]')).toHaveLength(1)
    expect(w.get('a').attributes('href')).toBe('https://severalnines.com/blog/x/')
  })

  it('链接在新标签页打开且不带 opener', () => {
    const a = render('web_search', { query: 'q' }, res(customSearch)).get('a')

    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toContain('noopener')
  })

  it('无法解析时回退原始文本；没有结果时显示搜索中；没有命中显示无结果', () => {
    expect(render('web_search', { query: 'q' }, res('搜索服务暂时不可用')).text()).toContain('搜索服务暂时不可用')
    expect(render('WebSearch', { query: 'q' }, undefined, false).text()).toContain('搜索中')
    expect(render('web_search', { query: 'q' }, res('搜索「q」没有找到结果，换个搜索词试试。')).text()).toContain('没有找到结果')
  })

  it('标题里的 HTML 作为文本显示，不会被解析', () => {
    const text = `搜索「q」，共 1 条结果：\n1. <img src=x onerror=alert(1)>\n   https://a.example/x`
    const w = render('web_search', { query: 'q' }, res(text))

    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toContain('<img src=x onerror=alert(1)>')
  })
})

describe('WebFetch / fetch_url', () => {
  it('显示可点击的 URL 与正文', () => {
    const w = render('fetch_url', { url: 'https://example.com/a', max_chars: 6000 }, res('以下是网页的外部内容\n\n正文内容'))

    expect(w.get('a').attributes('href')).toBe('https://example.com/a')
    expect(w.text()).toContain('正文内容')
  })

  it('WebFetch（Claude 原生）同样', () => {
    const w = render('WebFetch', { url: 'https://dev.mysql.com/doc/a.html', prompt: '总结' }, res('# 总结\n要点'))

    expect(w.get('a').attributes('href')).toBe('https://dev.mysql.com/doc/a.html')
    expect(w.text()).toContain('要点')
  })

  it('非 http(s) 的 URL 不渲染成链接', () => {
    const w = render('WebFetch', { url: 'javascript:alert(1)' }, res('x'))

    expect(w.find('a').exists()).toBe(false)
    expect(w.text()).toContain('javascript:alert(1)')
  })

  it('失败时显示错误面板', () => {
    const w = render('fetch_url', { url: 'https://example.com/a' }, err('这个地址不在本会话的搜索结果里'))

    expect(w.find('[data-testid="tool-pane-error"]').text()).toContain('不在本会话')
  })
})

describe('未知工具', () => {
  it('走通用正文：参数 JSON + 结果，失败时错误只出现一次', () => {
    const w = render('create_idea', { title: '冰箱门' }, err('标题重复'))

    expect(w.text()).toContain('title')
    expect(w.text().match(/标题重复/g)).toHaveLength(1)
  })
})
