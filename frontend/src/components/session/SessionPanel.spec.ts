import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  log: [] as string[],
  sentWith: [] as Array<{ sessionId: string; text: string; files?: File[] }>,
  sendFailure: null as Error | null,
  localAttachments: [] as unknown[],
  turnStatus: null as { status: string; turnId: string } | null,
}))

vi.mock('@/composables/useSessionStream', async () => {
  const { ref: vueRef } = await import('vue')
  return {
    useSessionStream: () => ({
      items: vueRef([]),
      turnStatus: vueRef(state.turnStatus),
      turns: vueRef(new Map()),
      addLocalUserMessage: (text: string, attachments?: unknown[]) => {
        state.log.push(`add:${text}`)
        state.localAttachments = attachments ?? []
        return 'local-1'
      },
      markTurnAccepted: () => {},
      removeLocalUserMessage: () => {
        state.log.push('remove')
      },
    }),
  }
})
vi.mock('@/composables/queries', () => ({
  useSendMessageMutation: (sessionId: () => string) => ({
    mutateAsync: async (body: { text: string; files?: File[] }) => {
      state.log.push('send')
      if (state.sendFailure) throw state.sendFailure
      state.sentWith.push({ sessionId: sessionId(), text: body.text, files: body.files })
      return { turn_id: 't1' }
    },
  }),
  useCancelSessionMutation: () => ({ mutateAsync: async () => {} }),
  useContinueSessionMutation: () => ({ mutateAsync: async () => ({ turn_id: 't2' }) }),
}))
vi.mock('./SessionTimeline.vue', () => ({ default: { name: 'SessionTimeline', render: () => null } }))

import SessionPanel from './SessionPanel.vue'

const textarea = (w: ReturnType<typeof mountPanel>) => w.get('textarea[name="message"]')

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(SessionPanel, {
    props: { sessionId: null, projectId: 'p1', ...props },
    attachTo: document.body,
  })
}

async function submit(w: ReturnType<typeof mountPanel>, text: string) {
  await textarea(w).setValue(text)
  await w.get('form').trigger('submit')
  await flushPromises()
}

describe('SessionPanel：没有会话时发送', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  it('没有会话、也没给 createSession：输入框和发送按钮禁用', () => {
    const w = mountPanel()
    expect(textarea(w).attributes('disabled')).toBeDefined()
    expect(w.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('没有会话但给了 createSession：输入框可用', () => {
    const w = mountPanel({ createSession: vi.fn() })
    expect(textarea(w).attributes('disabled')).toBeUndefined()
  })

  it('第一次发送先建会话，等会话 id 传进来后再乐观插入并发送', async () => {
    const w = mountPanel()
    const createSession = vi.fn(async () => {
      state.log.push('create')
      await w.setProps({ sessionId: 'new-session' })
      return 'new-session'
    })
    await w.setProps({ createSession })
    await submit(w, '你好')
    expect(createSession).toHaveBeenCalledTimes(1)
    expect(state.log).toEqual(['create', 'add:你好', 'send'])
    expect(state.sentWith).toEqual([{ sessionId: 'new-session', text: '你好' }])
  })

  it('已有会话时不再建会话', async () => {
    const createSession = vi.fn()
    const w = mountPanel({ sessionId: 's1', createSession })
    await submit(w, '你好')
    expect(createSession).not.toHaveBeenCalled()
    expect(state.sentWith).toEqual([{ sessionId: 's1', text: '你好' }])
  })

  it('建会话失败：显示错误，不发送、不留乐观消息', async () => {
    const createSession = vi.fn(async () => {
      throw new Error('没有已配置密钥的模型')
    })
    const w = mountPanel({ createSession })
    await submit(w, '你好')
    expect(w.text()).toContain('没有已配置密钥的模型')
    expect(state.log).toEqual([])
    expect(state.sentWith).toEqual([])
  })
})

describe('SessionPanel：sending 事件', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  const listeners = () => ({
    onSending: (value: boolean) => state.log.push(`sending:${value}`),
    onSent: () => state.log.push('sent'),
    onAccepted: () => state.log.push('accepted'),
  })

  it('点发送起（beforeSend 之前）发 sending(true)，发送成功后先 sent 再 sending(false)', async () => {
    const beforeSend = vi.fn(async () => {
      state.log.push('before')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend, ...listeners() })

    await submit(w, '你好')

    expect(state.log).toEqual(['sending:true', 'before', 'add:你好', 'send', 'sent', 'accepted', 'sending:false'])
  })

  it('beforeSend 失败：sending(false) 照发，没有 sent', async () => {
    const beforeSend = vi.fn(async () => {
      throw new Error('草稿还没有写入成功')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend, ...listeners() })

    await submit(w, '你好')

    expect(state.log).toEqual(['sending:true', 'sending:false'])
  })

  it('点 [继续]：发 accepted，但不发 sent（工作台靠 sent 把回退建议标成已处理，继续并没有把建议发出去）', async () => {
    state.turnStatus = { status: 'interrupted', turnId: 't0' }
    try {
      const w = mountPanel({ sessionId: 's1', ...listeners() })
      const button = w.findAll('button').find((b) => b.text() === '继续')!
      await button.trigger('click')
      await flushPromises()

      expect(state.log).toEqual(['sending:true', 'add:继续', 'accepted', 'sending:false'])
    } finally {
      state.turnStatus = null
    }
  })

  it('输入为空什么都不发', async () => {
    const w = mountPanel({ sessionId: 's1', ...listeners() })

    await submit(w, '   ')

    expect(state.log).toEqual([])
  })
})

describe('SessionPanel：beforeSend', () => {
  beforeEach(() => {
    state.log = []
    state.sentWith = []
    document.body.innerHTML = ''
  })

  it('发送前先调用 beforeSend（风格编辑用它把还没写出的编辑写进草稿）', async () => {
    const beforeSend = vi.fn(async () => {
      state.log.push('before')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend })

    await submit(w, '把配色改深一点')

    expect(beforeSend).toHaveBeenCalledTimes(1)
    expect(state.log).toEqual(['before', 'add:把配色改深一点', 'send'])
  })

  it('beforeSend 失败时不发送，显示原因', async () => {
    const beforeSend = vi.fn(async () => {
      throw new Error('草稿还没有写入成功')
    })
    const w = mountPanel({ sessionId: 's1', beforeSend })

    await submit(w, '你好')

    expect(state.sentWith).toEqual([])
    expect(w.text()).toContain('草稿还没有写入成功')
  })

  it('没给 beforeSend 时行为不变', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await submit(w, '你好')
    expect(state.sentWith).toEqual([{ sessionId: 's1', text: '你好' }])
  })
})


describe('SessionPanel：附件', () => {
  beforeEach(() => {
    // jsdom 的 File 和 Node 的 URL.createObjectURL 不兼容；附件预览地址在这里不重要。
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'data:,preview')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
    state.log = []
    state.sentWith = []
    state.sendFailure = null
    document.body.innerHTML = ''
  })

  async function attach(w: ReturnType<typeof mountPanel>, files: File[]) {
    const input = w.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: files, configurable: true })
    await input.trigger('change')
    await flushPromises()
  }

  const png = () => new File(['png'], 'a.png', { type: 'image/png' })
  const md = () => new File(['# hi'], 'notes.md', { type: 'text/markdown' })

  it('选中的附件显示成 chip，可以移除', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await attach(w, [png(), md()])
    expect(w.text()).toContain('a.png')
    expect(w.text()).toContain('notes.md')

    await w.get('button[aria-label="移除 notes.md"]').trigger('click')
    expect(w.text()).not.toContain('notes.md')
  })

  it('发送时把原始文件交给 sendMessage', async () => {
    const w = mountPanel({ sessionId: 's1' })
    const a = png()
    await attach(w, [a])
    await submit(w, '看图')

    expect(state.sentWith).toEqual([{ sessionId: 's1', text: '看图', files: [a] }])
    expect(w.text()).not.toContain('a.png')
  })

  it('乐观消息只给图片保留预览地址（评审 M2：文件的 data URL 可能有几十 MB）', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await attach(w, [png(), md()])
    await submit(w, '看看')

    expect(state.localAttachments).toEqual([
      { kind: 'image', name: 'a.png', size: 3, previewUrl: expect.any(String) },
      { kind: 'file', name: 'notes.md', size: 4 },
    ])
  })

  it('只有附件、没有文字也能发送', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await attach(w, [png()])
    await submit(w, '')

    expect(state.sentWith).toHaveLength(1)
  })

  it('发送失败时附件保留，显示错误', async () => {
    const w = mountPanel({ sessionId: 's1' })
    await attach(w, [md()])
    state.sendFailure = new Error('文件太大')
    await submit(w, '读一下')

    expect(w.text()).toContain('notes.md')
    expect(w.text()).toContain('文件太大')
  })

  it('超过上限的附件不发送，提示原因', async () => {
    const w = mountPanel({ sessionId: 's1' })
    const big = new File(['x'], 'big.png', { type: 'image/png' })
    Object.defineProperty(big, 'size', { value: 6 * 1024 * 1024 })
    await attach(w, [big])
    await submit(w, 'x')

    expect(state.sentWith).toEqual([])
    expect(w.text()).toContain('超过 5 MB')
  })

  it('images 模式：文件选择框只接受图片，非图片被拦下并提示', async () => {
    const w = mountPanel({ sessionId: 's1', attachmentAccept: 'images' })
    expect(w.get('input[type="file"]').attributes('accept')).toContain('image/png')

    await attach(w, [md()])

    expect(w.text()).not.toContain('notes.md')
    expect(w.text()).toContain('选题对话只支持图片')
  })
})
