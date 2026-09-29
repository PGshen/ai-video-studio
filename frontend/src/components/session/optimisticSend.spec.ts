import { describe, expect, it, vi } from 'vitest'
import { CONTINUE_TEXT, optimisticSend } from './optimisticSend'

describe('optimisticSend', () => {
  it('先乐观插入消息再发请求，成功时保留占位', async () => {
    const calls: string[] = []
    const add = vi.fn((text: string) => {
      calls.push(`add:${text}`)
      return 'local-0'
    })
    const remove = vi.fn()
    const send = vi.fn(async () => {
      calls.push('send')
    })

    await optimisticSend({ add, remove }, '你好', send)

    expect(calls).toEqual(['add:你好', 'send'])
    expect(remove).not.toHaveBeenCalled()
  })

  it('请求失败时撤回占位并把错误抛给调用方', async () => {
    const add = vi.fn(() => 'local-3')
    const remove = vi.fn()
    const error = new Error('409')

    await expect(
      optimisticSend({ add, remove }, CONTINUE_TEXT, async () => {
        throw error
      }),
    ).rejects.toBe(error)
    expect(remove).toHaveBeenCalledWith('local-3')
  })

  it('[继续] 发送的固定文本与后端 CONTINUE_TEXT 一致', () => {
    expect(CONTINUE_TEXT).toBe('继续')
  })
})
