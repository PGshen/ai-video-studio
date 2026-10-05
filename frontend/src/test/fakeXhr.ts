/** 测试用的假 `XMLHttpRequest`：记录请求，由测试手动触发进度与结束。 */
export class FakeXhr {
  static instances: FakeXhr[] = []
  static reset(): void {
    FakeXhr.instances = []
  }
  static get last(): FakeXhr {
    const xhr = FakeXhr.instances[FakeXhr.instances.length - 1]
    if (!xhr) throw new Error('没有发出任何 XHR 请求')
    return xhr
  }

  method = ''
  url = ''
  body: unknown = null
  headers: Record<string, string> = {}
  status = 0
  responseText = ''
  aborted = false
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeXhr.instances.push(this)
  }
  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string): void {
    this.headers[name] = value
  }
  send(body: unknown): void {
    this.body = body
  }
  abort(): void {
    this.aborted = true
    this.onabort?.()
  }

  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total })
  }
  respond(status: number, body: unknown): void {
    this.status = status
    this.responseText = typeof body === 'string' ? body : JSON.stringify(body)
    this.onload?.()
  }
  fail(): void {
    this.onerror?.()
  }
}
