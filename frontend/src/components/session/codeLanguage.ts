/** 按扩展名猜 shiki 的语言 id（读/写文件正文的语法高亮用）；未知一律 `text`。 */
const LANGUAGES: Record<string, string> = {
  md: 'markdown',
  markdown: 'markdown',
  py: 'python',
  ts: 'typescript',
  tsx: 'tsx',
  js: 'javascript',
  jsx: 'jsx',
  json: 'json',
  vue: 'vue',
  css: 'css',
  html: 'html',
  yml: 'yaml',
  yaml: 'yaml',
  sh: 'bash',
}

export function codeLanguage(path: string | undefined): string {
  if (!path) return 'text'
  const name = path.split('/').at(-1) ?? ''
  const dot = name.lastIndexOf('.')
  if (dot <= 0) return 'text'
  return LANGUAGES[name.slice(dot + 1).toLowerCase()] ?? 'text'
}
