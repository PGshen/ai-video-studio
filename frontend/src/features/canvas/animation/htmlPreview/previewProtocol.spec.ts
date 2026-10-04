import { describe, expect, it } from 'vitest'
import { parsePreviewMessage, seekMessage } from './previewProtocol'

const frame = {} as unknown
const other = {} as unknown

describe('seekMessage', () => {
  it('builds the message the preview page listens for', () => {
    expect(seekMessage(1.5)).toEqual({ type: 'seek', t: 1.5 })
  })
})

describe('parsePreviewMessage', () => {
  it('accepts ready and error messages from the iframe itself', () => {
    expect(parsePreviewMessage({ data: { type: 'ready', duration: 6 }, source: frame }, frame)).toEqual({
      type: 'ready',
      duration: 6,
    })
    expect(parsePreviewMessage({ data: { type: 'error', message: 'boom' }, source: frame }, frame)).toEqual({
      type: 'error',
      message: 'boom',
    })
  })

  it('ignores messages that did not come from this iframe', () => {
    expect(parsePreviewMessage({ data: { type: 'ready', duration: 6 }, source: other }, frame)).toBeNull()
    expect(parsePreviewMessage({ data: { type: 'ready', duration: 6 }, source: null }, frame)).toBeNull()
  })

  it('ignores a missing iframe window', () => {
    expect(parsePreviewMessage({ data: { type: 'ready', duration: 6 }, source: null }, null)).toBeNull()
  })

  it.each([
    null,
    'ready',
    42,
    {},
    { type: 'seek', t: 1 },
    { type: 'ready' },
    { type: 'ready', duration: 'x' },
    { type: 'error' },
    { type: 'error', message: 7 },
  ])('ignores malformed data %j', (data) => {
    expect(parsePreviewMessage({ data, source: frame }, frame)).toBeNull()
  })
})
