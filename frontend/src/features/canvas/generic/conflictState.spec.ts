import { describe, expect, it } from 'vitest'
import { edit, initBuffer, keepMine, loadLatest, saved, serverUpdate } from './conflictState'

describe('conflictState', () => {
  it('初始状态干净，没有未保存修改', () => {
    const state = initBuffer('hello')
    expect(state).toEqual({
      content: 'hello',
      savedContent: 'hello',
      dirty: false,
      conflict: false,
      incomingContent: null,
    })
  })

  it('编辑后 dirty 为 true；改回原内容 dirty 变回 false', () => {
    const s1 = edit(initBuffer('hello'), 'hello world')
    expect(s1.dirty).toBe(true)
    const s2 = edit(s1, 'hello')
    expect(s2.dirty).toBe(false)
  })

  it('缓冲区干净时，服务器更新直接采用，不产生冲突', () => {
    const clean = initBuffer('v1')
    const next = serverUpdate(clean, 'v2')
    expect(next).toEqual(initBuffer('v2'))
  })

  it('服务器内容和当前基线一样时忽略（不是真正的变化）', () => {
    const clean = initBuffer('v1')
    const next = serverUpdate(clean, 'v1')
    expect(next).toBe(clean)
  })

  it('缓冲区脏时收到服务器更新：进入冲突态，不覆盖本地内容', () => {
    const dirty = edit(initBuffer('v1'), 'my edit')
    const conflicted = serverUpdate(dirty, 'v2 from server')
    expect(conflicted).toEqual({
      content: 'my edit',
      savedContent: 'v1',
      dirty: true,
      conflict: true,
      incomingContent: 'v2 from server',
    })
  })

  it('[保留我的修改]：清除冲突，内容不变，基线换成服务器最新内容', () => {
    const dirty = edit(initBuffer('v1'), 'my edit')
    const conflicted = serverUpdate(dirty, 'v2 from server')
    const resolved = keepMine(conflicted)
    expect(resolved).toEqual({
      content: 'my edit',
      savedContent: 'v2 from server',
      dirty: true,
      conflict: false,
      incomingContent: null,
    })
  })

  it('非冲突态调用 keepMine 是 no-op', () => {
    const clean = initBuffer('v1')
    expect(keepMine(clean)).toBe(clean)
  })

  it('[载入最新]：丢弃本地改动，采用服务器内容，恢复干净态', () => {
    const dirty = edit(initBuffer('v1'), 'my edit')
    const conflicted = serverUpdate(dirty, 'v2 from server')
    const resolved = loadLatest(conflicted)
    expect(resolved).toEqual(initBuffer('v2 from server'))
  })

  it('保存成功：新内容成为新基线，dirty/conflict 复位', () => {
    const dirty = edit(initBuffer('v1'), 'my edit')
    const afterSave = saved(dirty, 'my edit')
    expect(afterSave).toEqual(initBuffer('my edit'))
  })
})
