import { describe, expect, it } from 'vitest'
import { editorLanguage, isTextFile, mediaKind } from './fileKind'

describe('isTextFile / editorLanguage', () => {
  it.each([
    ['topic/brief.md', true, 'markdown'],
    ['narrative/shots.json', true, 'json'],
    ['animation/scene.py', true, 'python'],
    ['animation/scenes/s-hook.js', true, 'javascript'],
    ['animation/assets/logo.svg', true, 'text'],
    ['notes.txt', true, 'text'],
    ['style/STYLE.md', true, 'markdown'],
  ] as const)('%s 是文本文件，语言为 %s', (path, expectedText, expectedLang) => {
    expect(isTextFile(path)).toBe(expectedText)
    expect(editorLanguage(path)).toBe(expectedLang)
  })

  it.each(['output/final.mp4', 'assets/logo.png', 'data.bin'])(
    '%s 是二进制文件',
    (path) => {
      expect(isTextFile(path)).toBe(false)
    },
  )

  it('没有扩展名的文件当二进制处理', () => {
    expect(isTextFile('README')).toBe(false)
  })
})

describe('mediaKind', () => {
  it.each([
    ['music/analysis.png', 'image'],
    ['a/b.JPG', 'image'],
    ['x.webp', 'image'],
    ['music/music.wav', 'audio'],
    ['narrative/audio/s-a.mp3', 'audio'],
    ['x.m4a', 'audio'],
    ['output/clip.mp4', 'video'],
    ['x.webm', 'video'],
  ] as const)('%s 可预览为 %s', (path, kind) => {
    expect(mediaKind(path)).toBe(kind)
  })

  it.each(['notes/a.md', 'logo.svg', 'data.bin', 'README'])('%s 不可媒体预览', (path) => {
    expect(mediaKind(path)).toBeNull()
  })
})
