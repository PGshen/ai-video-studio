/**
 * `vue-stream-markdown` 会把 Markdown 里的原始 HTML 渲染成真实元素，而它没有关闭这一行为的
 * 选项。模型输出不可信（网页里的提示注入会被模型照抄），所以交给它之前，把代码以外的 `<`
 * 转成 `&lt;`，让原始标签当文本显示。这是第一层防御；第二层见 `blockedHtml.ts`（渲染层拦截
 * 危险标签）。
 *
 * 「哪里是代码」必须和 Markdown 解析器一致，否则转义器以为是代码的地方解析器不认，就漏了：
 * - 围栏：开头缩进 ≤ 3 个空格的 3 个以上 `` ` `` 或 `~`；反引号围栏的信息串里不能再有反引号；
 *   关闭行必须同字符、不短于开头、后面只能是空白；流式输出里没闭合的围栏一直算代码。
 * - 行内代码：N 个反引号开头，被恰好 N 个反引号的一段关闭；反斜杠转义的反引号只是普通字符。
 * 拿不准的一律按「不是代码」处理（宁可多转义，也不漏转义）：缩进超过 3 个空格的围栏、跨行的
 * 行内代码都因此会多转义，代码里显示成 `&lt;`，这是可接受的代价。
 */
const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/
const FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/

/** 从 `from` 起找一段恰好 `length` 个反引号的 run，返回它的起点；找不到返回 -1。 */
function findClosingRun(line: string, from: number, length: number): number {
  let i = from
  while (i < line.length) {
    if (line[i] !== '`') {
      i += 1
      continue
    }
    let run = 1
    while (line[i + run] === '`') run += 1
    if (run === length) return i
    i += run
  }
  return -1
}

function escapeInline(line: string): string {
  let out = ''
  let i = 0
  while (i < line.length) {
    const ch = line[i]!
    if (ch === '\\' && i + 1 < line.length) {
      // 反斜杠转义：下一个字符是普通字符（包括反引号）；`<` 照样转义。
      const next = line[i + 1]!
      out += ch + (next === '<' ? '&lt;' : next)
      i += 2
    } else if (ch === '`') {
      let run = 1
      while (line[i + run] === '`') run += 1
      const close = findClosingRun(line, i + run, run)
      if (close === -1) {
        out += line.slice(i, i + run) // 没有配对：这串反引号只是文本。
        i += run
      } else {
        out += line.slice(i, close + run) // 行内代码原样保留。
        i = close + run
      }
    } else {
      out += ch === '<' ? '&lt;' : ch
      i += 1
    }
  }
  return out
}

export function escapeRawHtml(text: string): string {
  if (!text.includes('<')) return text
  let fence: { char: string; length: number } | null = null
  return text
    .split('\n')
    .map((line) => {
      if (fence !== null) {
        const close = FENCE_CLOSE.exec(line)
        if (close && close[1]![0] === fence.char && close[1]!.length >= fence.length) fence = null
        return line
      }
      const open = FENCE_OPEN.exec(line)
      if (open) {
        const marker = open[1]!
        const info = open[2]!
        if (marker[0] !== '`' || !info.includes('`')) {
          fence = { char: marker[0]!, length: marker.length }
          return line
        }
      }
      return escapeInline(line)
    })
    .join('\n')
}
