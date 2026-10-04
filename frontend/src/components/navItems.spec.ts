import { describe, expect, it } from 'vitest'
import { NAV_MAIN } from './navItems'

describe('NAV_MAIN', () => {
  it('把风格库放在项目和设置之间', () => {
    expect(NAV_MAIN.map((item) => item.title)).toEqual(['选题', '项目', '风格库', '设置'])
    expect(NAV_MAIN.find((item) => item.title === '风格库')?.url).toBe('/styles')
  })

  it('每一项都有图标和唯一的地址', () => {
    expect(NAV_MAIN.every((item) => item.icon !== undefined)).toBe(true)
    expect(new Set(NAV_MAIN.map((item) => item.url)).size).toBe(NAV_MAIN.length)
  })
})
