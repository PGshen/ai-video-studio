import { parseServerTime } from '@/components/session/turnMeta'

const pad = (n: number) => String(n).padStart(2, '0')

/**
 * 快照时间的紧凑显示（本地时区的 `MM-DD HH:mm`）。服务器返回的是没有时区后缀的 UTC，
 * 解析方式见 `parseServerTime`；解析失败时原样返回。
 */
export function formatSnapshotTime(iso: string): string {
  const date = parseServerTime(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
