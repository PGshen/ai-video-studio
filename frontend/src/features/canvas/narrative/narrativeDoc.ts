/**
 * 叙事阶段画布的纯逻辑（M3 T10）：把 `narrative/narrative.json` 的原始文本
 * 解析成镜头卡片要显示的结构，并做一层和后端 `stages/narrative/schema.py`
 * 一致的"轻量校验标记"。
 *
 * 校验的权威来源是后端 `validate_narrative` 工具；这里只是让用户在画布上
 * 一眼看出哪个镜头有问题，不是第二套规则：只检查卡片本来就要显示的东西
 * （旁白/beats 是否为空、cue_text 拼起来是否覆盖旁白、transition 取值），
 * 归一化规则与 `engines/tts/text_normalize.py` 保持一致。
 *
 * 和 `features/canvas/animation/narrativeScenes.ts` 一样，`narrative.json`
 * 不是合法 JSON 时把 `SyntaxError` 原样抛出，由调用方 try/catch 展示。
 */

/** `narrative.json` 在工作区里的固定路径（叙事阶段自己的产物，不是 `upstream/`）。 */
export const NARRATIVE_PATH = 'narrative/narrative.json'

export const TRANSITIONS = ['continue', 'transform', 'reveal', 'replace', 'exit'] as const

export interface NarrativeBeat {
  cue_text: string
  visual_action: string
  emphasis: string
  /** 原样保留（可能不在 `TRANSITIONS` 里，由 `sceneIssues` 报出）。 */
  transition: string
}

export interface NarrativeScene {
  id: string
  narration: string
  visual_intent: string
  beats: NarrativeBeat[]
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function parseBeat(raw: unknown): NarrativeBeat {
  const beat = isRecord(raw) ? raw : {}
  return {
    cue_text: asString(beat.cue_text),
    visual_action: asString(beat.visual_action),
    emphasis: asString(beat.emphasis),
    transition: asString(beat.transition),
  }
}

/** 按出现顺序解析全部有字符串 `id` 的镜头；缺失的文本字段用空串。 */
export function parseNarrativeDoc(raw: string): NarrativeScene[] {
  const parsed: unknown = JSON.parse(raw)
  if (!isRecord(parsed) || !Array.isArray(parsed.scenes)) return []
  const scenes: NarrativeScene[] = []
  for (const entry of parsed.scenes as unknown[]) {
    if (!isRecord(entry) || typeof entry.id !== 'string') continue
    scenes.push({
      id: entry.id,
      narration: asString(entry.narration),
      visual_intent: asString(entry.visual_intent),
      beats: Array.isArray(entry.beats) ? entry.beats.map(parseBeat) : [],
    })
  }
  return scenes
}

const PUNCTUATION: Record<string, string> = {
  '，': ',',
  '。': '.',
  '！': '!',
  '？': '?',
  '：': ':',
  '；': ';',
  '（': '(',
  '）': ')',
  '“': '"',
  '”': '"',
  '‘': "'",
  '’': "'",
}

/** 对齐 `normalize_alignment_text`：NFKC、全角标点转半角、去空白。 */
export function normalizeAlignmentText(text: string): string {
  const mapped = Array.from(text.normalize('NFKC'), (char) => PUNCTUATION[char] ?? char).join('')
  return mapped.replace(/\s+/g, '')
}

/** 一个镜头当前存在的问题（中文短句）；空数组表示没发现问题。 */
export function sceneIssues(scene: NarrativeScene): string[] {
  const issues: string[] = []
  if (scene.narration.trim() === '') issues.push('旁白为空')
  if (scene.visual_intent.trim() === '') issues.push('缺少 visual_intent')
  if (scene.beats.length === 0) {
    issues.push('还没有 beats')
    return issues
  }
  scene.beats.forEach((beat, index) => {
    const label = `beat ${index + 1}`
    if (beat.cue_text.trim() === '') issues.push(`${label} 缺少 cue_text`)
    if (beat.visual_action.trim() === '') issues.push(`${label} 缺少 visual_action`)
    if (beat.emphasis.trim() === '') issues.push(`${label} 缺少 emphasis`)
    if (!(TRANSITIONS as readonly string[]).includes(beat.transition)) {
      issues.push(`${label} 的 transition 不合法：${beat.transition || '（空）'}`)
    }
  })
  const joined = normalizeAlignmentText(scene.beats.map((b) => b.cue_text).join(''))
  if (scene.narration.trim() !== '' && joined !== normalizeAlignmentText(scene.narration)) {
    issues.push('beats 的 cue_text 没有完整覆盖旁白')
  }
  return issues
}

/** 整份文档里重复出现的镜头 id（后端要求 id 唯一）。 */
export function duplicateSceneIds(scenes: readonly NarrativeScene[]): string[] {
  const seen = new Set<string>()
  const duplicated = new Set<string>()
  for (const scene of scenes) {
    if (seen.has(scene.id)) duplicated.add(scene.id)
    seen.add(scene.id)
  }
  return [...duplicated]
}
