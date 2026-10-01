/**
 * `vue-stream-markdown` 会把 Markdown 里的原始 HTML 渲染成真实元素（实测 `<script>` 会进 DOM），
 * 而它没有关闭这一行为的选项。模型输出不可信，所以在交给它之前，把代码以外的 `<` 转成 `&lt;`，
 * 让原始标签当文本显示。围栏代码块（``` / ~~~，流式中没闭合的也算）和行内代码保持原样——
 * 代码里转义会显示成 `&lt;`。
 */
const FENCE = /^\s{0,3}(`{3,}|~{3,})/
const INLINE_CODE = /(`[^`\n]*`)/

function escapeLine(line: string): string {
  return line
    .split(INLINE_CODE)
    .map((part, index) => (index % 2 === 1 ? part : part.replaceAll('<', '&lt;')))
    .join('')
}

export function escapeRawHtml(text: string): string {
  if (!text.includes('<')) return text
  let fence: string | null = null
  return text
    .split('\n')
    .map((line) => {
      const match = FENCE.exec(line)
      if (fence === null) {
        if (match) {
          fence = match[1]![0]!
          return line
        }
        return escapeLine(line)
      }
      if (match && match[1]![0] === fence) fence = null
      return line
    })
    .join('\n')
}
