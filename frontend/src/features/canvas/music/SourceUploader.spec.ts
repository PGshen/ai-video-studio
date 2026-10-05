import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'

const state = vi.hoisted(() => ({
  calls: [] as Array<{ file: File; signal?: AbortSignal; onProgress?: (l: number, t: number) => void }>,
  resolve: undefined as undefined | ((value: unknown) => void),
  reject: undefined as undefined | ((error: unknown) => void),
}))

vi.mock('@/composables/queries', () => ({
  useUploadMusicSourceMutation: () => ({
    mutateAsync: (input: { file: File; signal?: AbortSignal; onProgress?: (l: number, t: number) => void }) => {
      state.calls.push(input)
      return new Promise((resolve, reject) => {
        state.resolve = resolve
        state.reject = reject
        input.signal?.addEventListener('abort', () => {
          const error = new Error('上传已取消')
          error.name = 'AbortError'
          reject(error)
        })
      })
    },
  }),
}))

import SourceUploader from './SourceUploader.vue'

const mountUploader = (props: Partial<{ busy: boolean; hasSource: boolean }> = {}) =>
  mount(SourceUploader, { props: { projectId: 'p1', busy: false, hasSource: false, ...props } })

async function pick(wrapper: ReturnType<typeof mountUploader>, file: File): Promise<void> {
  const input = wrapper.find('[data-testid="music-upload-input"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

const song = (name = 'a.mp3', size = 1000) => {
  const file = new File(['x'], name)
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('SourceUploader', () => {
  beforeEach(() => {
    state.calls = []
  })

  it('空闲时显示选择文件；已上传时是“更换歌曲”并提示需要重新分析', () => {
    expect(mountUploader().find('[data-testid="music-upload-button"]').text()).toBe('选择文件')
    const replace = mountUploader({ hasSource: true })
    expect(replace.find('[data-testid="music-upload-button"]').text()).toBe('更换歌曲')
    expect(replace.find('[data-testid="music-uploader-replace-hint"]').text()).toContain('重新分析')
  })

  it('上传中显示进度并随 onProgress 更新，成功后发出 uploaded', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, song())
    expect(state.calls).toHaveLength(1)
    expect(wrapper.find('[data-testid="music-upload-progress"]').exists()).toBe(true)
    state.calls[0]!.onProgress!(30, 120)
    await flushPromises()
    expect(wrapper.find('[data-testid="music-upload-percent"]').text()).toContain('25%')
    const source = { filename: 'source.mp3', size: 1000, sha256: 'x', duration: 10 }
    state.resolve!(source)
    await flushPromises()
    expect(wrapper.find('[data-testid="music-upload-done"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="music-upload-progress"]').exists()).toBe(false)
    expect(wrapper.emitted('uploaded')![0]).toEqual([source])
  })

  it('服务端的 422 中文原因原样显示，之后可以再传', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, song())
    state.reject!(new ApiError(422, '音频时长 2.0 秒，需要在 5–600 秒之间'))
    await flushPromises()
    expect(wrapper.find('[data-testid="music-upload-error"]').text()).toBe(
      '音频时长 2.0 秒，需要在 5–600 秒之间',
    )
    expect(wrapper.find('[data-testid="music-upload-button"]').attributes('disabled')).toBeUndefined()
  })

  it('取消会中止请求并显示已取消，不当成错误', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, song())
    await wrapper.find('[data-testid="music-upload-cancel"]').trigger('click')
    await flushPromises()
    expect(state.calls[0]!.signal!.aborted).toBe(true)
    expect(wrapper.find('[data-testid="music-upload-cancelled"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="music-upload-error"]').exists()).toBe(false)
  })

  it('客户端先挡错误的扩展名与超大文件，不发请求', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, song('a.mp4'))
    expect(wrapper.find('[data-testid="music-upload-error"]').text()).toContain('格式')
    await pick(wrapper, song('a.mp3', 150 * 1024 * 1024 + 1))
    expect(wrapper.find('[data-testid="music-upload-error"]').text()).toContain('150 MB')
    expect(state.calls).toHaveLength(0)
  })

  it('有一轮在跑时禁用并说明原因，拖入文件也不上传', async () => {
    const wrapper = mountUploader({ busy: true })
    expect(wrapper.find('[data-testid="music-upload-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="music-upload-busy"]').exists()).toBe(true)
    await wrapper.find('[data-testid="music-uploader"]').trigger('drop', {
      dataTransfer: { files: [song()] },
    })
    await flushPromises()
    expect(state.calls).toHaveLength(0)
  })

  it('拖入文件会上传', async () => {
    const wrapper = mountUploader()
    await wrapper.find('[data-testid="music-uploader"]').trigger('drop', {
      dataTransfer: { files: [song('b.wav')] },
    })
    await flushPromises()
    expect(state.calls.map((c) => c.file.name)).toEqual(['b.wav'])
  })
})
