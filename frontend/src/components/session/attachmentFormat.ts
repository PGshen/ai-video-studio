/** 附件大小的显示：B / kB / MB，保留一位小数。 */
export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} kB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
