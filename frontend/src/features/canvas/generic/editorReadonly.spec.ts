import { describe, expect, it } from 'vitest'
import { computeReadonly } from './editorReadonly'

describe('computeReadonly', () => {
  it('可写：既没在运行、也不是 upstream', () => {
    expect(computeReadonly({ busy: false, isUpstream: false })).toEqual({
      readonly: false,
      reason: null,
    })
  })

  it('agent 运行中：只读，原因是 busy', () => {
    expect(computeReadonly({ busy: true, isUpstream: false })).toEqual({
      readonly: true,
      reason: 'busy',
    })
  })

  it('upstream 下的文件：只读，原因是 upstream', () => {
    expect(computeReadonly({ busy: false, isUpstream: true })).toEqual({
      readonly: true,
      reason: 'upstream',
    })
  })

  it('两者都成立时优先报告 busy（运行中最紧迫）', () => {
    expect(computeReadonly({ busy: true, isUpstream: true })).toEqual({
      readonly: true,
      reason: 'busy',
    })
  })
})
