/**
 * 语速规则（计划 M5 T12）：项目倍速 0.5–2.0（对应火山引擎相对值 -50 至 100），与后端
 * `db/repo/settings.py::SPEECH_RATE_MIN/MAX` 一致；两端已在 M5 T8 用真实合成验证过
 * （`docs/references/volcengine-tts.md`）。语音设置页和项目设置对话框共用。
 */

export const SPEED_MIN = 0.5
export const SPEED_MAX = 2

/** 输入框文本 → 语速；不是有限数字或超出范围返回 `null`。 */
export function parseSpeed(text: string): number | null {
  const trimmed = text.trim()
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(trimmed)) return null
  const value = Number(trimmed)
  return Number.isFinite(value) && value >= SPEED_MIN && value <= SPEED_MAX ? value : null
}

export function speedError(text: string): string | null {
  return parseSpeed(text) === null ? `语速必须是 ${SPEED_MIN}–${SPEED_MAX} 之间的数字` : null
}
