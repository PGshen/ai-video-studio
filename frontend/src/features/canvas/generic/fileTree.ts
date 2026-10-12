/**
 * Turns the flat `GET /files` path list into a directory tree for `FileTree.vue`.
 * Pure functions so the view only handles rendering and expand state.
 */
import type { FileEntry } from '@/types/api'

export interface FileNode {
  kind: 'file'
  name: string
  path: string
  readonly: boolean
}

export interface DirNode {
  kind: 'dir'
  name: string
  path: string
  children: TreeNode[]
}

export type TreeNode = FileNode | DirNode

export interface VisibleRow {
  node: TreeNode
  depth: number
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

function sortNodes(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1
    return collator.compare(a.name, b.name)
  })
  for (const node of nodes) {
    if (node.kind === 'dir') sortNodes(node.children)
  }
}

export function buildFileTree(files: FileEntry[]): TreeNode[] {
  const root: TreeNode[] = []
  const dirs = new Map<string, DirNode>()

  for (const file of files) {
    const parts = file.path.split('/')
    let siblings = root
    for (let i = 0; i < parts.length - 1; i++) {
      const dirPath = parts.slice(0, i + 1).join('/')
      let dir = dirs.get(dirPath)
      if (!dir) {
        dir = { kind: 'dir', name: parts[i], path: dirPath, children: [] }
        dirs.set(dirPath, dir)
        siblings.push(dir)
      }
      siblings = dir.children
    }
    siblings.push({ kind: 'file', name: parts[parts.length - 1], path: file.path, readonly: file.readonly })
  }

  sortNodes(root)
  return root
}

export function flattenVisible(nodes: TreeNode[], expanded: ReadonlySet<string>, depth = 0): VisibleRow[] {
  const rows: VisibleRow[] = []
  for (const node of nodes) {
    rows.push({ node, depth })
    if (node.kind === 'dir' && expanded.has(node.path)) {
      rows.push(...flattenVisible(node.children, expanded, depth + 1))
    }
  }
  return rows
}

export function ancestorDirs(path: string): string[] {
  const parts = path.split('/')
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/'))
}
