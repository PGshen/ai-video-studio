/**
 * 风格接口的内存假实现（测试用）：在测试里
 * `vi.mock('@/api/endpoints', async () => (await import('@/test/fakeStyleApi')).endpoints)`
 * 把 `api/endpoints.ts` 换掉，行为和后端 `api/styles.py` 一致——草稿与正式版本分开、保存才覆盖、
 * 找不到抛 404 的 `ApiError`。
 */
import { ApiError } from '@/api/http'
import { readStyleMeta } from '@/features/styles/styleFrontmatter'
import type { DraftStatusOut, StyleOut, StyleSummaryOut } from '@/types/api'

type Files = Record<string, string>

export const server = {
  saved: new Map<string, Files>(),
  drafts: new Map<string, Files>(),
  defaultId: null as string | null,
  /** 设置后 `saveStyleDraft` 抛出它。 */
  saveError: null as ApiError | null,
  /** 设置后 `writeDraftFile` 抛出它。 */
  writeError: null as ApiError | null,
  /** 有对话轮次在跑的风格 id（草稿状态的 `busy`）。 */
  busy: new Set<string>(),
  writes: [] as { id: string; path: string; content: string }[],
  nextId: 1,
}

export function resetServer(): void {
  server.saved.clear()
  server.drafts.clear()
  server.defaultId = null
  server.saveError = null
  server.writeError = null
  server.busy.clear()
  server.writes = []
  server.nextId = 1
}

export function entry(name: string, category = '概念传记', description = '一套风格'): string {
  return `---\nname: ${name}\ndescription: ${description}\ncategory: ${category}\n---\n\n# ${name}\n`
}

/** 往「服务端」放一套已保存的风格。 */
export function seedStyle(id: string, name: string, extra: Files = {}, category = '概念传记'): void {
  server.saved.set(id, { 'STYLE.md': entry(name, category), ...extra })
}

export function seedDraft(id: string, files: Files): void {
  server.drafts.set(id, { ...files })
}

const notFound = (id: string) => new ApiError(404, `风格不存在：${id}`)

function status(id: string): DraftStatusOut {
  const draft = server.drafts.get(id)
  if (!draft) throw notFound(id)
  const saved = server.saved.get(id)
  const dirty = !saved || JSON.stringify(sorted(saved)) !== JSON.stringify(sorted(draft))
  return {
    id,
    is_new: !saved,
    dirty,
    files: Object.keys(draft).sort(),
    busy: server.busy.has(id),
  }
}

const sorted = (files: Files) => Object.entries(files).sort(([a], [b]) => a.localeCompare(b))

function detail(id: string): StyleOut {
  const files = server.saved.get(id)
  if (!files) throw notFound(id)
  const meta = readStyleMeta(files['STYLE.md'] ?? '')
  return {
    id,
    name: meta.name,
    category: meta.category || '未分类',
    description: meta.description || null,
    files: { ...files },
    is_default: server.defaultId === id,
    modified_at: '2026-10-01T00:00:00Z',
  }
}

export const endpoints = {
  async listStyles(): Promise<StyleSummaryOut[]> {
    const drafts = [...server.drafts.entries()]
      .filter(([id]) => !server.saved.has(id))
      .map(([id, files]): StyleSummaryOut => {
        const meta = readStyleMeta(files['STYLE.md'] ?? '')
        const names = Object.keys(files)
        return {
          id,
          name: meta.name || '未命名风格',
          category: meta.category || '未分类',
          description: meta.description || null,
          reference_count: names.filter((n) => n.startsWith('references/')).length,
          exemplar_count: names.filter((n) => n.startsWith('exemplars/')).length,
          is_default: false,
          has_draft: true,
          is_new: true,
          modified_at: '2026-10-01T00:00:00Z',
        }
      })
    const saved = [...server.saved.keys()].map((id) => {
      const d = detail(id)
      const names = Object.keys(d.files)
      return {
        id,
        name: d.name,
        category: d.category,
        description: d.description,
        reference_count: names.filter((n) => n.startsWith('references/')).length,
        exemplar_count: names.filter((n) => n.startsWith('exemplars/')).length,
        is_default: d.is_default,
        has_draft: server.drafts.has(id),
        is_new: false,
        modified_at: d.modified_at,
      }
    })
    return [...saved, ...drafts]
  },
  async getStyle(id: string): Promise<StyleOut> {
    return detail(id)
  },
  async createStyle(): Promise<DraftStatusOut> {
    const id = `new${server.nextId++}`
    server.drafts.set(id, { 'STYLE.md': entry('新风格', '未分类', '一句话说明') })
    return status(id)
  },
  async duplicateStyle(id: string): Promise<StyleOut> {
    const source = detail(id)
    const copyId = `copy${server.nextId++}`
    server.saved.set(copyId, {
      ...source.files,
      'STYLE.md': entry(`${source.name}（副本）`, source.category),
    })
    return detail(copyId)
  },
  async deleteStyle(id: string): Promise<void> {
    if (!server.saved.delete(id) && !server.drafts.delete(id)) throw notFound(id)
    server.drafts.delete(id)
    if (server.defaultId === id) server.defaultId = null
  },
  async openStyleDraft(id: string): Promise<DraftStatusOut> {
    if (!server.drafts.has(id)) {
      const saved = server.saved.get(id)
      if (!saved) throw notFound(id)
      server.drafts.set(id, { ...saved })
    }
    return status(id)
  },
  async getStyleDraft(id: string): Promise<DraftStatusOut> {
    return status(id)
  },
  async readDraftFile(id: string, path: string): Promise<string> {
    const text = server.drafts.get(id)?.[path]
    if (text === undefined) throw notFound(path)
    return text
  },
  async writeDraftFile(id: string, path: string, content: string): Promise<DraftStatusOut> {
    if (server.writeError) throw server.writeError
    const draft = server.drafts.get(id)
    if (!draft) throw notFound(id)
    draft[path] = content
    server.writes.push({ id, path, content })
    return status(id)
  },
  async deleteDraftFile(id: string, path: string): Promise<void> {
    const draft = server.drafts.get(id)
    if (!draft || !(path in draft)) throw notFound(path)
    delete draft[path]
  },
  async saveStyleDraft(id: string): Promise<StyleOut> {
    if (server.saveError) throw server.saveError
    const draft = server.drafts.get(id)
    if (!draft) throw notFound(id)
    server.saved.set(id, { ...draft })
    server.drafts.delete(id)
    return detail(id)
  },
  async discardStyleDraft(id: string): Promise<void> {
    if (!server.drafts.delete(id) && !server.saved.has(id)) throw notFound(id)
  },
  async patchSettings(patch: { default_style_preset_id?: string | null }) {
    if ('default_style_preset_id' in patch) server.defaultId = patch.default_style_preset_id ?? null
    return { default_style_preset_id: server.defaultId }
  },
}
