/** 「在本机文件管理器中打开」按钮的文字，按平台起名（后端和浏览器在同一台机器上）。 */
export function revealLabel(platform: string = navigator.userAgent): string {
  if (/Mac/i.test(platform)) return '在 Finder 中打开'
  if (/Win/i.test(platform)) return '在文件夹中打开'
  return '在文件管理器中打开'
}
