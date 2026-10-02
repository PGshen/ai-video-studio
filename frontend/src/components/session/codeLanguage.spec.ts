import { describe, expect, it } from 'vitest'
import { codeLanguage } from './codeLanguage'

describe('codeLanguage', () => {
  it.each([
    ['topic/brief.md', 'markdown'],
    ['scenes/scene_01.py', 'python'],
    ['a/b.ts', 'typescript'],
    ['x.tsx', 'tsx'],
    ['x.js', 'javascript'],
    ['narrative/narrative.json', 'json'],
    ['App.vue', 'vue'],
    ['style.css', 'css'],
    ['index.html', 'html'],
    ['ci.yml', 'yaml'],
    ['ci.yaml', 'yaml'],
    ['run.sh', 'bash'],
  ])('%s → %s', (path, language) => {
    expect(codeLanguage(path)).toBe(language)
  })

  it('扩展名大小写不敏感；未知或没有扩展名时回退 text', () => {
    expect(codeLanguage('README.MD')).toBe('markdown')
    expect(codeLanguage('notes.xyz')).toBe('text')
    expect(codeLanguage('Makefile')).toBe('text')
    expect(codeLanguage('dir.d/file')).toBe('text')
    expect(codeLanguage(undefined)).toBe('text')
  })
})
