import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScenePlayback, type PlaylistItem } from './useScenePlayback'

class FakeAudio {
  static instances: FakeAudio[] = []
  src = ''
  paused = true
  playRejects = false
  private listeners: Record<string, Array<() => void>> = {}
  constructor() {
    FakeAudio.instances.push(this)
  }
  addEventListener(type: string, fn: () => void): void {
    ;(this.listeners[type] ??= []).push(fn)
  }
  removeEventListener(type: string, fn: () => void): void {
    this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)
  }
  play(): Promise<void> {
    if (this.playRejects) return Promise.reject(new Error('NotAllowedError'))
    this.paused = false
    return Promise.resolve()
  }
  pause(): void {
    this.paused = true
  }
  emit(type: string): void {
    for (const fn of this.listeners[type] ?? []) fn()
  }
}

const items = (...ids: string[]): PlaylistItem[] => ids.map((id) => ({ id, url: `/audio/${id}.mp3` }))

function setup(initial: PlaylistItem[]) {
  const list = ref(initial)
  const scope = effectScope()
  const playback = scope.run(() => useScenePlayback(() => list.value))!
  const audio = () => FakeAudio.instances[0]!
  return { list, scope, playback, audio }
}

const tick = () => Promise.resolve()

describe('useScenePlayback', () => {
  beforeEach(() => {
    FakeAudio.instances = []
    vi.stubGlobal('Audio', FakeAudio)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('初始空闲：没有当前镜头，也不在播放', () => {
    const { playback } = setup(items('a', 'b'))
    expect(playback.currentId.value).toBeNull()
    expect(playback.isPlaying.value).toBe(false)
  })

  it('toggle 从第一个镜头开始播', async () => {
    const { playback, audio } = setup(items('a', 'b'))
    playback.toggle()
    await tick()
    expect(playback.currentId.value).toBe('a')
    expect(playback.isPlaying.value).toBe(true)
    expect(audio().src).toBe('/audio/a.mp3')
  })

  it('一个镜头播完自动接下一个，最后一个播完回到空闲', async () => {
    const { playback, audio } = setup(items('a', 'b'))
    playback.toggle()
    audio().emit('ended')
    await tick()
    expect(playback.currentId.value).toBe('b')
    expect(audio().src).toBe('/audio/b.mp3')
    expect(playback.isPlaying.value).toBe(true)
    audio().emit('ended')
    await tick()
    expect(playback.currentId.value).toBeNull()
    expect(playback.isPlaying.value).toBe(false)
  })

  it('再次 toggle 暂停并保留当前镜头；再点从暂停处继续而不是重新加载', async () => {
    const { playback, audio } = setup(items('a', 'b'))
    playback.toggle()
    audio().emit('ended') // 到 b
    await tick()
    playback.toggle()
    expect(playback.isPlaying.value).toBe(false)
    expect(playback.currentId.value).toBe('b')
    expect(audio().paused).toBe(true)
    const srcBefore = audio().src
    playback.toggle()
    await tick()
    expect(playback.isPlaying.value).toBe(true)
    expect(playback.currentId.value).toBe('b')
    expect(audio().src).toBe(srcBefore)
  })

  it('播放被浏览器拒绝或音频出错：停下来，不留在"播放中"', async () => {
    const { playback, audio } = setup(items('a', 'b'))
    playback.toggle()
    await tick()
    audio().emit('error')
    expect(playback.isPlaying.value).toBe(false)

    const second = setup(items('a'))
    // 第二个 FakeAudio 实例：让 play() 被拒绝。
    second.playback.toggle()
    const el = FakeAudio.instances[1]!
    el.playRejects = true
    second.playback.toggle() // 暂停
    second.playback.toggle() // 继续 → 被拒绝
    await tick()
    await tick()
    expect(second.playback.isPlaying.value).toBe(false)
  })

  it('当前镜头从列表里消失（回滚/删除）时停止', async () => {
    const { playback, list, audio } = setup(items('a', 'b'))
    playback.toggle()
    await tick()
    list.value = items('b')
    await tick()
    expect(playback.currentId.value).toBeNull()
    expect(playback.isPlaying.value).toBe(false)
    expect(audio().paused).toBe(true)
  })

  it('toggle(startId)：空闲时从指定镜头开始往后播', async () => {
    const { playback, audio } = setup(items('a', 'b', 'c'))
    playback.toggle('b')
    await tick()
    expect(playback.currentId.value).toBe('b')
    expect(audio().src).toBe('/audio/b.mp3')
    audio().emit('ended')
    await tick()
    expect(playback.currentId.value).toBe('c')
  })

  it('startId 不在列表里：从头开始', async () => {
    const { playback } = setup(items('a', 'b'))
    playback.toggle('zzz')
    await tick()
    expect(playback.currentId.value).toBe('a')
  })

  it('暂停后选了别的镜头再点播放：从选中的镜头重新开始；选中的还是暂停所在的则继续', async () => {
    const { playback, audio } = setup(items('a', 'b', 'c'))
    playback.toggle('a')
    playback.toggle() // 暂停在 a
    const srcBefore = audio().src
    playback.toggle('a')
    await tick()
    expect(audio().src).toBe(srcBefore)
    playback.toggle() // 再暂停
    playback.toggle('c')
    await tick()
    expect(playback.currentId.value).toBe('c')
    expect(audio().src).toBe('/audio/c.mp3')
    expect(playback.isPlaying.value).toBe(true)
  })

  it('jumpTo：播放中跳到另一个镜头往后播；暂停/空闲时不动；同一个镜头不重载', async () => {
    const { playback, audio } = setup(items('a', 'b', 'c'))
    playback.jumpTo('b')
    expect(playback.isPlaying.value).toBe(false)
    playback.toggle()
    await tick()
    const srcA = audio().src
    playback.jumpTo('a')
    expect(audio().src).toBe(srcA)
    playback.jumpTo('c')
    await tick()
    expect(playback.currentId.value).toBe('c')
    expect(audio().src).toBe('/audio/c.mp3')
    playback.toggle() // 暂停
    playback.jumpTo('a')
    expect(playback.currentId.value).toBe('c')
  })

  it('列表为空时 toggle 什么也不做', () => {
    const { playback } = setup([])
    playback.toggle()
    expect(playback.isPlaying.value).toBe(false)
  })

  it('作用域销毁时停止播放', async () => {
    const { playback, scope, audio } = setup(items('a'))
    playback.toggle()
    await tick()
    scope.stop()
    expect(audio().paused).toBe(true)
  })
})
