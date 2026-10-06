import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/http'

const state = vi.hoisted(() => ({
  uploads: [] as File[],
  deletes: 0,
  uploadError: undefined as unknown,
  deleteError: undefined as unknown,
}))

vi.mock('@/composables/queries', () => ({
  useUploadMusicLyricsMutation: () => ({
    mutateAsync: (input: { file: File }) => {
      state.uploads.push(input.file)
      return state.uploadError
        ? Promise.reject(state.uploadError)
        : Promise.resolve({ lines: 12, sha256: 'x' })
    },
  }),
  useDeleteMusicLyricsMutation: () => ({
    mutateAsync: () => {
      state.deletes += 1
      return state.deleteError ? Promise.reject(state.deleteError) : Promise.resolve()
    },
  }),
}))

import LyricsUploader from './LyricsUploader.vue'

const mountUploader = (props: Partial<{ busy: boolean; lines: number }> = {}) =>
  mount(LyricsUploader, { props: { projectId: 'p1', busy: false, lines: 0, ...props } })

async function pick(wrapper: ReturnType<typeof mountUploader>, name: string, size = 100) {
  const file = new File(['x'], name)
  Object.defineProperty(file, 'size', { value: size })
  const input = wrapper.find('[data-testid="lyrics-input"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

describe('LyricsUploader', () => {
  beforeEach(() => {
    state.uploads = []
    state.deletes = 0
    state.uploadError = undefined
    state.deleteError = undefined
  })

  it('没有歌词时是“上传歌词（可选）”，没有删除按钮', () => {
    const wrapper = mountUploader()
    expect(wrapper.find('[data-testid="lyrics-button"]').text()).toContain('上传歌词')
    expect(wrapper.find('[data-testid="lyrics-delete"]').exists()).toBe(false)
  })

  it('已有歌词：显示句数，按钮变成“更换歌词”，出现“删除歌词”', () => {
    const wrapper = mountUploader({ lines: 12 })
    expect(wrapper.text()).toContain('12 句')
    expect(wrapper.find('[data-testid="lyrics-button"]').text()).toBe('更换歌词')
    expect(wrapper.find('[data-testid="lyrics-delete"]').exists()).toBe(true)
  })

  it('选 .lrc 文件就上传，成功后提示让 agent 重新读歌词并发出 uploaded', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, '歌.lrc')
    expect(state.uploads).toHaveLength(1)
    expect(wrapper.find('[data-testid="lyrics-done"]').text()).toContain('12 句')
    expect(wrapper.emitted('uploaded')).toHaveLength(1)
  })

  it('扩展名或大小不对时不发请求，显示中文原因', async () => {
    const wrapper = mountUploader()
    await pick(wrapper, 'a.txt')
    expect(state.uploads).toHaveLength(0)
    expect(wrapper.find('[data-testid="lyrics-error"]').text()).toContain('.lrc')
  })

  it('服务端的 422 原因原样显示', async () => {
    state.uploadError = new ApiError(422, '没有找到时间戳：只支持带时间戳的 LRC')
    const wrapper = mountUploader()
    await pick(wrapper, 'a.lrc')
    expect(wrapper.find('[data-testid="lyrics-error"]').text()).toContain('时间戳')
    expect(wrapper.emitted('uploaded')).toBeUndefined()
  })

  it('删除歌词调用删除接口', async () => {
    const wrapper = mountUploader({ lines: 3 })
    await wrapper.find('[data-testid="lyrics-delete"]').trigger('click')
    await flushPromises()
    expect(state.deletes).toBe(1)
  })

  it('有一轮在跑时禁用上传与删除', () => {
    const wrapper = mountUploader({ busy: true, lines: 3 })
    expect(wrapper.find('[data-testid="lyrics-button"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="lyrics-delete"]').attributes('disabled')).toBeDefined()
  })
})
