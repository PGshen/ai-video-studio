import { describe, expect, it } from 'vitest'
import { ancestorDirs, buildFileTree, flattenVisible } from './fileTree'

const entry = (path: string, readonly = false) => ({ path, readonly })

describe('buildFileTree', () => {
  it('按路径分段组装目录，目录在前、文件在后，各自按名称排序', () => {
    const tree = buildFileTree([
      entry('animation/scenes/s02.js'),
      entry('animation/global.js'),
      entry('README.md'),
      entry('animation/scenes/s01.js'),
      entry('animation/lib/kit.js'),
    ])
    expect(tree.map((n) => n.name)).toEqual(['animation', 'README.md'])
    const animation = tree[0]
    expect(animation.kind).toBe('dir')
    if (animation.kind !== 'dir') return
    expect(animation.children.map((n) => n.name)).toEqual(['lib', 'scenes', 'global.js'])
    const scenes = animation.children[1]
    if (scenes.kind !== 'dir') throw new Error('scenes should be dir')
    expect(scenes.path).toBe('animation/scenes')
    expect(scenes.children.map((n) => n.path)).toEqual([
      'animation/scenes/s01.js',
      'animation/scenes/s02.js',
    ])
  })

  it('文件节点保留 readonly 标记', () => {
    const [upstream] = buildFileTree([entry('upstream/topic/brief.md', true)])
    if (upstream.kind !== 'dir') throw new Error('expected dir')
    const [topic] = upstream.children
    if (topic.kind !== 'dir') throw new Error('expected dir')
    expect(topic.children[0]).toMatchObject({ kind: 'file', readonly: true })
  })

  it('数字按自然顺序排序', () => {
    const tree = buildFileTree([entry('s10.js'), entry('s2.js'), entry('s1.js')])
    expect(tree.map((n) => n.name)).toEqual(['s1.js', 's2.js', 's10.js'])
  })
})

describe('flattenVisible', () => {
  const tree = buildFileTree([
    entry('animation/scenes/s01.js'),
    entry('animation/global.js'),
    entry('README.md'),
  ])

  it('只展开 expanded 集合里的目录，并带上层级深度', () => {
    const rows = flattenVisible(tree, new Set(['animation']))
    expect(rows.map((r) => [r.node.path, r.depth])).toEqual([
      ['animation', 0],
      ['animation/scenes', 1],
      ['animation/global.js', 1],
      ['README.md', 0],
    ])
  })

  it('全部折叠时只显示顶层', () => {
    expect(flattenVisible(tree, new Set()).map((r) => r.node.path)).toEqual(['animation', 'README.md'])
  })
})

describe('ancestorDirs', () => {
  it('返回文件所有祖先目录', () => {
    expect(ancestorDirs('a/b/c.js')).toEqual(['a', 'a/b'])
    expect(ancestorDirs('c.js')).toEqual([])
  })
})
