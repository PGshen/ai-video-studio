import { describe, expect, it } from 'vitest'
import {
  COVERAGE_THRESHOLD,
  computeDubbing,
  computeReadiness,
  overallCoverage,
  parseTimingDoc,
} from './timingStatus'

function timingEntry(id: string, coverage = 1) {
  return {
    id,
    audio_path: `narrative/audio/${id}.mp3`,
    audio_hash: 'sha256:abc',
    duration_seconds: 2,
    beats: [
      { start_seconds: 0, end_seconds: 1 },
      { start_seconds: 1, end_seconds: 2 },
    ],
    word_timestamps: [],
    alignment_coverage: coverage,
  }
}

const raw = (...entries: object[]) => JSON.stringify({ scenes: entries })

describe('parseTimingDoc', () => {
  it('按 id 索引并解析 beats 起止时间', () => {
    const parsed = parseTimingDoc(raw(timingEntry('s-a', 0.5)))
    expect(parsed['s-a']).toEqual({
      id: 's-a',
      audio_path: 'narrative/audio/s-a.mp3',
      audio_hash: 'sha256:abc',
      duration_seconds: 2,
      beats: [
        { start_seconds: 0, end_seconds: 1 },
        { start_seconds: 1, end_seconds: 2 },
      ],
      alignment_coverage: 0.5,
    })
  })

  it('字段缺失时用默认值，过滤没有 id 的条目', () => {
    const parsed = parseTimingDoc(JSON.stringify({ scenes: [{ id: 's-a' }, {}, null] }))
    expect(Object.keys(parsed)).toEqual(['s-a'])
    expect(parsed['s-a']).toEqual({
      id: 's-a',
      audio_path: '',
      audio_hash: '',
      duration_seconds: 0,
      beats: [],
      alignment_coverage: 0,
    })
  })

  it('不是合法 JSON 时把 SyntaxError 原样抛出', () => {
    expect(() => parseTimingDoc('{oops')).toThrow(SyntaxError)
  })
})

describe('computeDubbing', () => {
  it('timing.json 不存在时全部未配音', () => {
    expect(computeDubbing(['s-a', 's-b'], null).map((d) => d.state)).toEqual(['missing', 'missing'])
  })

  it('按镜头顺序判断是否配过音，忽略 timing 里已不在叙事中的镜头', () => {
    const dubbing = computeDubbing(['s-b', 's-a'], raw(timingEntry('s-a'), timingEntry('s-gone')))
    expect(dubbing.map((d) => [d.id, d.state])).toEqual([
      ['s-b', 'missing'],
      ['s-a', 'dubbed'],
    ])
    expect(dubbing[1].timing?.audio_path).toBe('narrative/audio/s-a.mp3')
  })
})

describe('computeDubbing 的过期判断（TD-36）', () => {
  const dubbedWith = (narration: string, voice = 'zizi', speed = 1) => ({
    ...timingEntry('s-a'),
    narration,
    voice,
    speed,
  })
  const current = (narration: string, voice = 'zizi', speed = 1) => ({
    narrations: { 's-a': narration },
    voice,
    speed,
  })

  it('旁白、音色、语速都没变时是已配音', () => {
    const [d] = computeDubbing(['s-a'], raw(dubbedWith('甲乙')), current('甲乙'))
    expect(d.state).toBe('dubbed')
  })

  it('配音之后旁白改了，判为已过期', () => {
    const [d] = computeDubbing(['s-a'], raw(dubbedWith('甲乙')), current('甲乙丙'))
    expect(d.state).toBe('stale')
    expect(d.timing?.id).toBe('s-a')
  })

  it('音色或语速改了，判为已过期', () => {
    expect(computeDubbing(['s-a'], raw(dubbedWith('甲乙')), current('甲乙', 'other'))[0].state).toBe('stale')
    expect(computeDubbing(['s-a'], raw(dubbedWith('甲乙')), current('甲乙', 'zizi', 1.2))[0].state).toBe('stale')
  })

  it('旧条目没有记录配音输入时不判过期，也不传当前值时不判过期', () => {
    expect(computeDubbing(['s-a'], raw(timingEntry('s-a')), current('随便'))[0].state).toBe('dubbed')
    expect(computeDubbing(['s-a'], raw(dubbedWith('甲乙')))[0].state).toBe('dubbed')
  })
})

describe('overallCoverage', () => {
  it('对已配音镜头取平均，一个都没有时为 null', () => {
    expect(overallCoverage(computeDubbing(['s-a'], null))).toBeNull()
    const dubbing = computeDubbing(['s-a', 's-b', 's-c'], raw(timingEntry('s-a', 1), timingEntry('s-b', 0.5)))
    expect(overallCoverage(dubbing)).toBe(0.75)
  })
})

describe('computeReadiness', () => {
  const allDubbed = computeDubbing(['s-a', 's-b'], raw(timingEntry('s-a'), timingEntry('s-b')))

  it('全部有效、已配音、覆盖率达标时可以定稿', () => {
    expect(computeReadiness({ sceneCount: 2, issueSceneCount: 0, dubbing: allDubbed })).toEqual({
      ready: true,
      reasons: [],
    })
  })

  it('有配音已过期的镜头时不能定稿', () => {
    const stale = computeDubbing(['s-a', 's-b'], raw(timingEntry('s-a'), timingEntry('s-b')))
    stale[1] = { ...stale[1], state: 'stale' }
    const readiness = computeReadiness({ sceneCount: 2, issueSceneCount: 0, dubbing: stale })
    expect(readiness.ready).toBe(false)
    expect(readiness.reasons).toEqual(['1 个镜头的配音已过期（旁白、音色或语速在配音后改过），需要重新配音'])
  })

  it('没有镜头时不能定稿', () => {
    expect(computeReadiness({ sceneCount: 0, issueSceneCount: 0, dubbing: [] })).toEqual({
      ready: false,
      reasons: ['还没有镜头'],
    })
  })

  it('校验问题、未配音、覆盖率过低分别给出原因', () => {
    const partial = computeDubbing(['s-a', 's-b'], raw(timingEntry('s-a', COVERAGE_THRESHOLD - 0.3)))
    const readiness = computeReadiness({ sceneCount: 2, issueSceneCount: 1, dubbing: partial })
    expect(readiness.ready).toBe(false)
    expect(readiness.reasons).toEqual([
      '1 个镜头有校验问题',
      '1 个镜头还没有配音',
      '对齐覆盖率 50% 低于 80%',
    ])
  })
})
