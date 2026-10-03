/** 关键帧放大预览里前后切换：到头尾停住（不循环），`length` 为 0 时保持 0。 */
export function stepKeyframe(index: number, delta: 1 | -1, length: number): number {
  if (length <= 0) return 0
  return Math.min(length - 1, Math.max(0, index + delta))
}
