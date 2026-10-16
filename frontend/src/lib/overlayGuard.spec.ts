import { afterEach, describe, expect, it, vi } from 'vitest'
import { ignoreMarkdownOverlay } from './overlayGuard'

describe('ignoreMarkdownOverlay', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('弹层内的外部交互被拦下，其他目标不受影响', () => {
    document.body.innerHTML = '<div id="stream-markdown-overlay"><button id="in"></button></div><button id="out"></button>'
    const inside = vi.fn()
    const outside = vi.fn()
    ignoreMarkdownOverlay({
      target: null,
      detail: { originalEvent: { target: document.getElementById('in') } as unknown as Event },
      preventDefault: inside,
    })
    ignoreMarkdownOverlay({
      target: document.getElementById('out'),
      preventDefault: outside,
    })
    expect(inside).toHaveBeenCalledOnce()
    expect(outside).not.toHaveBeenCalled()
  })
})
