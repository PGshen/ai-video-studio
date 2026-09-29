/**
 * 叙事阶段的配音状态（M3 T10）：把 `narrative/timing.json` 的原始文本和当前
 * 镜头 id 列表对照，算出每个镜头"是否配过音"、对齐覆盖率，以及能不能定稿。
 *
 * 决策（计划 T10）：`timing.json` 不存 narration 的哈希/文本，前端无法判断
 * "配过音之后旁白又改了"，所以这里只有"未配音/已配音"两态；配音过期检测
 * 登记在 tech-debt 里，出现真实需求再做（`audio_hash` 目前只是音频字节的
 * 哈希，不是"旁白+音色+语速"的哈希，设计 §5.2 的完整版留待后续）。
 *
 * `timing.json` 文件不存在时调用方传 `null`；存在但不是合法 JSON 时让
 * `SyntaxError` 原样抛出（同 `narrativeDoc.ts` 的约定）。
 */

export const TIMING_PATH = 'narrative/timing.json'

/** 对齐覆盖率的定稿阈值：先写死，需要调整时改这里（计划"不包含"一节）。 */
export const COVERAGE_THRESHOLD = 0.8

export interface BeatTiming {
  start_seconds: number
  end_seconds: number
}

export interface SceneTiming {
  id: string
  audio_path: string
  audio_hash: string
  duration_seconds: number
  beats: BeatTiming[]
  alignment_coverage: number
}

export type DubbingState = 'missing' | 'dubbed'

export interface SceneDubbing {
  id: string
  state: DubbingState
  timing: SceneTiming | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function parseTimingDoc(raw: string): Record<string, SceneTiming> {
  const parsed: unknown = JSON.parse(raw)
  const result: Record<string, SceneTiming> = {}
  if (!isRecord(parsed) || !Array.isArray(parsed.scenes)) return result
  for (const entry of parsed.scenes as unknown[]) {
    if (!isRecord(entry) || typeof entry.id !== 'string') continue
    result[entry.id] = {
      id: entry.id,
      audio_path: str(entry.audio_path),
      audio_hash: str(entry.audio_hash),
      duration_seconds: num(entry.duration_seconds),
      beats: Array.isArray(entry.beats)
        ? (entry.beats as unknown[]).map((b) => ({
            start_seconds: num(isRecord(b) ? b.start_seconds : 0),
            end_seconds: num(isRecord(b) ? b.end_seconds : 0),
          }))
        : [],
      alignment_coverage: num(entry.alignment_coverage),
    }
  }
  return result
}

/** 按叙事镜头顺序给出每个镜头的配音状态；`timingRaw` 为 `null` 表示文件还不存在。 */
export function computeDubbing(
  sceneIds: readonly string[],
  timingRaw: string | null,
): SceneDubbing[] {
  const timings = timingRaw === null ? {} : parseTimingDoc(timingRaw)
  return sceneIds.map((id) => {
    const timing = timings[id] ?? null
    return { id, state: timing === null ? 'missing' : 'dubbed', timing }
  })
}

/** 已配音镜头的平均对齐覆盖率；一个都没配过音时为 `null`。 */
export function overallCoverage(dubbing: readonly SceneDubbing[]): number | null {
  const covered = dubbing.filter((d) => d.timing !== null)
  if (covered.length === 0) return null
  const sum = covered.reduce((acc, d) => acc + (d.timing?.alignment_coverage ?? 0), 0)
  return sum / covered.length
}

export interface Readiness {
  ready: boolean
  /** 暂时不能定稿的原因（中文短句）；`ready` 时为空。 */
  reasons: string[]
}

/**
 * 叙事能否定稿（设计 §5.2 的定稿条件，前端提示用；后端 `finalize` 不强制）：
 * 有镜头、没有校验问题、每个镜头都配过音、平均对齐覆盖率不低于阈值。
 */
export function computeReadiness(params: {
  sceneCount: number
  issueSceneCount: number
  dubbing: readonly SceneDubbing[]
}): Readiness {
  const reasons: string[] = []
  if (params.sceneCount === 0) {
    reasons.push('还没有镜头')
    return { ready: false, reasons }
  }
  if (params.issueSceneCount > 0) reasons.push(`${params.issueSceneCount} 个镜头有校验问题`)
  const missing = params.dubbing.filter((d) => d.state === 'missing').length
  if (missing > 0) reasons.push(`${missing} 个镜头还没有配音`)
  const coverage = overallCoverage(params.dubbing)
  if (coverage !== null && coverage < COVERAGE_THRESHOLD) {
    reasons.push(
      `对齐覆盖率 ${Math.round(coverage * 100)}% 低于 ${Math.round(COVERAGE_THRESHOLD * 100)}%`,
    )
  }
  return { ready: reasons.length === 0, reasons }
}
