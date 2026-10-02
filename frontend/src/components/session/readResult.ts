/**
 * Claude 原生 `Read` 的结果是 `行号→内容`（cat -n 风格）逐行带前缀；自建 `read_file` 没有。
 * 每一行都带前缀且行号连续才认作 Read 的输出，返回起始行号和去掉前缀的代码；否则 `null`。
 */
const NUMBERED = /^\s*(\d+)[→\t](.*)$/

export function parseNumberedLines(text: string): { startLine: number; code: string } | null {
  if (text === '') return null
  const lines = text.split('\n')
  if (lines.length > 1 && lines.at(-1) === '') lines.pop() // 末尾换行不算一行
  const code: string[] = []
  let startLine: number | undefined
  let expected: number | undefined
  for (const line of lines) {
    const match = NUMBERED.exec(line)
    if (!match) return null
    const lineNumber = Number(match[1])
    if (expected !== undefined && lineNumber !== expected) return null
    startLine ??= lineNumber
    expected = lineNumber + 1
    code.push(match[2]!)
  }
  return { startLine: startLine!, code: code.join('\n') }
}
